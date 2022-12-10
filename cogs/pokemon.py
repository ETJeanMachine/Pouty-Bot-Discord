import discord
import asyncpg
import matplotlib.pyplot as plt
from aiohttp import ClientSession
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord import app_commands
from typing import Dict, Any, List, Literal, Optional, Union
from uuid import UUID, uuid4


@dataclass
class TourneyData:
    id: UUID
    channel: Union[int, discord.TextChannel, discord.VoiceChannel]
    guild: Union[int, discord.Guild]
    interval: timedelta = timedelta(24)
    start_time: datetime = datetime.now()
    current_gen: int = 1
    past_gens: List[int] = field(default_factory=lambda: [])
    vote_on_gen: bool = False
    active: bool = False

    async def db_insert(self, db: Union[asyncpg.Connection, asyncpg.Pool]):
        await db.execute(
            """insert into pokemon_tourney.data 
            values ($1, $2, $3, $4, $5, $6, $7, $8, $9);""",
            self.id,
            self.channel.id,
            self.guild.id,
            self.start_time,
            self.interval,
            self.current_gen,
            self.past_gens,
            self.vote_on_gen,
            self.active,
        )

    async def db_update(self, db: Union[asyncpg.Connection, asyncpg.Pool]):
        await db.execute(
            """update pokemon_tourney.data 
            set current_gen=$2, active=$3 where id=$1;""",
            self.id,
            self.current_gen,
            self.active,
        )


@dataclass
class CombatantData:
    id: UUID
    end_time: datetime
    dex_no: int
    tourney: Union[UUID, TourneyData]
    message: Union[int, discord.Message, discord.PartialMessage, None] = None


class VoteData:
    id: UUID
    user: Union[int, discord.User]
    rank: str
    tourney: Union[UUID, TourneyData]
    combatant: Union[UUID, CombatantData]


class StartView(discord.ui.View):
    def __init__(self, *, bot: commands.Bot, t_data: TourneyData):
        super().__init__(timeout=None)
        self.bot = bot
        self.t_data = t_data
        self.tourney = None

    @discord.ui.button(label="Start Tourney", disabled=False, emoji="▶️")
    async def start_button(self, inter: discord.Interaction, btn: discord.ui.Button):
        self.t_data.active = True
        self.t_data.start_time = datetime.now()
        await self.t_data.db_insert(self.bot.db)
        self.tourney = Tourney(self.t_data, self.bot.db)
        await inter.response.edit_message(
            embed=None, view=None, content="Tourney has been successfully generated!"
        )

    @property
    def embed(self):
        embed = discord.Embed(
            title="Start Pokemon Tourney",
            description="Confirm that the below settings are correct:",
        )
        embed.add_field(
            name="Tourney Channel", value=self.t_data.channel.mention, inline=True
        )
        embed.add_field(
            name="Vote on Next Generation",
            value=f"`{self.t_data.vote_on_gen}`",
            inline=True,
        )
        embed.add_field(
            name="Time Interval Between Votes",
            value=f"{int(self.t_data.interval.total_seconds()) // 3600} hours",
            inline=False,
        )
        return embed

    async def start(self, inter: discord.Interaction):
        await inter.response.send_message(embed=self.embed, view=self, ephemeral=True)


class VoteView(discord.ui.View):
    pass


class Tourney:
    def __init__(self, data: TourneyData, db: Union[asyncpg.Connection, asyncpg.Pool]):
        self.data = data
        self.active_pokemon = List[CombatantData]
        self.db = db

    async def current_votes(self, db: Union[asyncpg.Connection, asyncpg.Pool]) -> None:
        """This method is called when the cog has been reloaded, and the `active_votes` attribute is empty. It pulls any
        active votes from the vote table, or if none are active, generates the next votes.

        Args:
            db (Union[asyncpg.Connection, asyncpg.Pool]): The database that this method pulls from.
        """
        if len(self.active_pokemon) != 0:
            return
        records = await db.fetch(
            """
            SELECT t.* FROM pokemon.vote t 
            WHERE t.tourney_id = $1 AND t.end_time > $2 ORDER BY dex_no;
        """,
            self.id,
            datetime.now(),
        )
        if len(records) == 0:
            await self.next_votes(db)
        else:
            for r in records:
                vote = VoteData(
                    id=r.get("id"),
                    votes=r.get("votes"),
                    end_time=r.get("end_time"),
                    dex_no=r.get("dex_no"),
                    tourney=self.id,
                )
                self.active_pokemon.append(vote)

    async def next_pokemon(self, db: Union[asyncpg.Connection, asyncpg.Pool]):
        """This method progresses to the next set of Pokemon in the progression of the generation order,
        and changes the `active_votes` attribute. If active votes is empty, it populates it with the initial votes.

        Args:
            db (Union[asyncpg.Connection, asyncpg.Pool]): The database that this method pulls from.
        """
        client = ClientSession()
        next_pkmn = None
        # called when starting a new tourney.
        if len(self.active_pokemon) == 0:
            gen_response = await (
                await client.get(
                    f"https://pokeapi.co/api/v2/generation/{self.data.current_gen}/"
                )
            ).json()
            # getting the first pokemon of the generation.
            next_pkmn = await (
                await client.get(gen_response["pokemon_species"][0]["url"])
            ).json()
        else:
            next_pkmn = await (
                await client.get(self.active_pokemon[len(self.active_pokemon) - 1])
            ).json()
            if next_pkmn["generation"]["name"] != current_gen:
                current_gen = next_pkmn["generation"]["name"]
            self.active_pokemon.clear()
        dex_no = next_pkmn["id"]
        prev_names = []
        # We have at least 10 active votes per session.
        while True:
            # adding the "next" (last) pokemon to the list.
            vote = VoteData(
                id=uuid4(),
                votes=[0, 0, 0, 0, 0, 0],
                end_time=datetime.now() + self.data.interval,
                dex_no=dex_no,
            )
            vote.tourney = self
            self.active_pokemon.append(vote)
            # advancing to the next mon
            dex_no += 1
            prev_names.append(next_pkmn["name"])
            next_pkmn = await (
                await client.get(f"https://pokeapi.co/api/v2/pokemon-species/{dex_no}")
            ).json()
            # checking if this pokemon has an evolution, if so, we run down it's concurrent dex line.
            evolves_from = next_pkmn["evolves_from_species"]
            if not (
                (evolves_from != None and evolves_from["name"] in prev_names)
                or len(self.active_pokemon) < 10
            ):
                break
        for vote in self.active_pokemon:
            await vote.create_in_store(db)
        await client.close()

    async def next_generation():
        pass

    def __eq__(self, __o: object) -> bool:
        if isinstance(__o, Tourney):
            return self.data.id == __o.data.id
        return False


class Pokemon(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: Union[asyncpg.Connection, asyncpg.Pool] = bot.db
        self.active_tourneys: List[Tourney] = []
        self.bot.tree.remove_command("start")

    async def load_tourneys(self):
        records = await self.db.fetch("""select * from pokemon_tourney.vote;""")
        for r in records:
            t_data = TourneyData(
                id=r.get("id"),
                channel=discord.Object(r.get("channel_id")),
                guild=discord.Object(r.get("guild_id")),
                interval=r.get("time_interval"),
                start_time=r.get("start_time"),
                current_gen=r.get("current_gen"),
                auto_gen=r.get("auto_gen"),
                active=r.get("active"),
            )
            tourney = Tourney(t_data, self.db)
            self.active_tourneys.append(tourney)

    async def init_db(self):
        sql = """
            create schema if not exists pokemon_tourney;
            create table if not exists pokemon_tourney.data
            (
            	id            uuid                                                 not null primary key,
            	channel_id    bigint                                               not null,
            	guild_id      bigint                                               not null,
            	start_time    timestamp with time zone default now()               not null,
            	time_interval interval                                             not null,
            	current_gen   integer                  default 1                   not null,
            	past_gens     integer[]                default ARRAY []::integer[] not null,
            	vote_on_gen   boolean                  default false               not null,
            	active        boolean                  default false               not null
            );
            create table if not exists pokemon_tourney.combatant
            (
            	id         uuid                     not null primary key,
            	end_time   timestamp with time zone not null,
            	dex_no     integer                  not null,
            	message_id bigint,
            	tourney_id uuid                     not null references pokemon_tourney.data on delete cascade
            );
            create table if not exists pokemon_tourney.vote
            (
            	id           integer not null primary key,
            	user_id      bigint  not null,
            	rank         char    not null,
            	tourney_id   uuid    not null references pokemon_tourney.data on delete cascade,
            	combatant_id uuid    not null references pokemon_tourney.combatant on delete cascade
            )
         """
        await self.db.execute(sql)

    async def cog_load(self):
        await self.init_db()
        await self.load_tourneys()

    @tasks.loop(hours=1)
    async def check_tourney_status(self):
        remove_tourneys = []
        for tourney in self.active_tourneys:
            if tourney.data.active == False:
                remove_tourneys.append(tourney)
                tourney.data.db_update(self.db)
                self.active_tourneys.remove(tourney)

    pokemon = app_commands.Group(
        name="pokemon", description="Commands for ranking Pokemon."
    )

    @pokemon.command(
        name="start", description="Starts a new tourney for ranking Pokemon."
    )
    @app_commands.describe(
        channel="The channel for sending tourney messages in. Should be isolated from other channels.",
        vote_on_gen="Whether or not to vote on generations. Defaults to false, where it will run from Gen 1 up.",
        interval="The frequency by which to run votes. Defaults to 24 hours.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def pokemon_start(
        self,
        inter: discord.Interaction,
        channel: Union[discord.TextChannel, discord.VoiceChannel],
        vote_on_gen: Literal["True", "False"] = "False",
        interval: app_commands.Range[int, 1, 48] = 24,
    ):
        # First checking if there is an active tourney in this guild. If there is, we must throw an exception.
        records = await self.db.fetch(
            """select from pokemon_tourney.data t where t.active = true and t.guild_id = $1;""",
            inter.guild.id,
        )
        if len(records) != 0:
            raise app_commands.AppCommandError(
                "Tourney already started in guild, stop tourney to begin a new one."
            )
        t_data = TourneyData(
            id=uuid4(),
            channel=channel,
            guild=inter.guild,
            interval=timedelta(hours=interval),
            vote_on_gen=True if vote_on_gen == "True" else False,
        )
        start_view = StartView(bot=self.bot, t_data=t_data)
        await start_view.start(inter)
        await start_view.wait()
        self.active_tourneys.append(start_view.tourney)


async def setup(bot: commands.Bot):
    await bot.add_cog(Pokemon(bot))
