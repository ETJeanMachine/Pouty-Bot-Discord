import asyncpg
import discord
import matplotlib.pyplot as plt
import time
from aiohttp import ClientSession
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from discord import app_commands
from enum import Enum
from typing import Dict, Any, List, Literal, Optional, Union
from uuid import UUID, uuid4


@dataclass
class TourneyData:
    id: UUID
    channel: Union[int, discord.TextChannel, discord.VoiceChannel]
    guild: Union[int, discord.Guild]
    interval: timedelta = timedelta(24)
    start_time: datetime = datetime.utcnow()
    current_gen: int = -1
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

    async def db_insert(self, db: Union[asyncpg.Connection, asyncpg.Pool]):
        await db.execute(
            """insert into pokemon_tourney.combatant 
            values ($1, $2, $3, $4, $5);""",
            self.id,
            self.end_time,
            self.dex_no,
            None if self.message == None else self.message.id,
            self.tourney.id,
        )

    async def db_update(self, db: Union[asyncpg.Connection, asyncpg.Pool]):
        await db.execute(
            """update pokemon_tourney.combatant
            set message_id=$2 where id=$1; 
            """,
            self.id,
            None if self.message == None else self.message.id,
        )


@dataclass
class VoteData:
    id: UUID
    user: Union[int, discord.User]
    rank: str
    tourney: Union[UUID, TourneyData]
    combatant: Union[UUID, CombatantData]

    async def db_insert():
        pass

    async def db_update():
        pass


class Type(Enum):
    normal = discord.Colour.from_str("#a8a878")
    fighting = discord.Colour.from_str("#c03028")
    flying = discord.Colour.from_str("#a890f0")
    poison = discord.Colour.from_str("#9f40a0")
    ground = discord.Colour.from_str("#e0c068")
    rock = discord.Colour.from_str("#b8a039")
    bug = discord.Colour.from_str("#a8b920")
    ghost = discord.Colour.from_str("#705898")
    steel = discord.Colour.from_str("#b8b8d0")
    fire = discord.Colour.from_str("#f08030")
    water = discord.Colour.from_str("#6790f0")
    grass = discord.Colour.from_str("#78c84f")
    electric = discord.Colour.from_str("#f8d130")
    psychic = discord.Colour.from_str("#f85888")
    ice = discord.Colour.from_str("#98d8d8")
    dragon = discord.Colour.from_str("#7038f8")
    dark = discord.Colour.from_str("#705848")
    fairy = discord.Colour.from_str("#ee99ac")
    unknown = discord.Colour.from_str("#67a090")
    shadow = discord.Colour.from_str("#604e82")


class StartView(discord.ui.View):
    def __init__(self, *, bot: commands.Bot, t_data: TourneyData):
        super().__init__(timeout=None)
        self.bot = bot
        self.t_data = t_data
        self.tourney = None

    @discord.ui.button(label="Start Tourney", disabled=False, emoji="▶️")
    async def start_button(self, inter: discord.Interaction, btn: discord.ui.Button):
        self.t_data.active = True
        self.t_data.start_time = datetime.utcnow()
        await self.t_data.db_insert(self.bot.db)
        self.tourney = Tourney(self.t_data, self.bot)
        await inter.response.edit_message(
            embed=None, view=None, content="Tourney has been successfully generated!"
        )
        await self.tourney.next_pkmn()
        await self.tourney.send_views()

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


class CombatantView(discord.ui.View):
    options = [
        discord.SelectOption(label="S"),
        discord.SelectOption(label="A"),
        discord.SelectOption(label="B"),
        discord.SelectOption(label="C"),
        discord.SelectOption(label="D"),
        discord.SelectOption(label="F"),
    ]

    def __init__(self, *, bot: commands.Bot, c_data: CombatantData):
        self.bot = bot
        self.c_data = c_data
        self.species = None
        self.default_form = None
        self.alternate_forms = []
        super().__init__(timeout=None)

    async def get_data(self):
        client = ClientSession()
        self.species = await (
            await client.get(
                f"https://pokeapi.co/api/v2/pokemon-species/{self.c_data.dex_no}"
            )
        ).json()
        for var in self.species["varieties"]:
            form = await (await client.get(var["pokemon"]["url"])).json()
            if var["is_default"]:
                self.default_form = form
            else:
                self.alternate_forms.append(form)
        await client.close()

    @discord.ui.select(placeholder="Select A Ranking!", options=options)
    async def rank_select(self, inter: discord.Interaction, select: discord.ui.Select):
        if self.c_data.end_time < datetime.utcnow():
            select.disabled = True
            return
        # TODO

    def embed(self, form):
        embed = discord.Embed(title=self.species["names"][8]["name"])
        sprites = form["sprites"]
        embed.set_image(url=sprites["other"]["official-artwork"]["front_default"])
        embed.set_author(
            name=f"Pokédex Entry #{self.c_data.dex_no}",
            icon_url=sprites["front_default"],
        )
        embed.colour = Type[form["types"][0]["type"]["name"]].value
        return embed

    async def start(self):
        await self.get_data()
        await self.c_data.tourney.channel.send(
            view=self, embed=self.embed(self.default_form)
        )


class GenerationView(discord.ui.View):
    # TODO

    def __init__(self, *, bot: commands.Bot, t_data: TourneyData):
        super().__init__(timeout=None)


class Tourney:
    def __init__(self, data: TourneyData, bot: commands.Bot):
        self.data = data
        self.bot = bot
        self.active_pokemon: List[CombatantData] = []
        self.db: Union[asyncpg.Connection, asyncpg.Pool] = bot.db

    async def progress_tourney(self):
        if self.data.current_gen == -1:
            if not self.data.vote_on_gen:
                if len(self.data.past_gens) == 0:
                    self.data.current_gen = 1
                else:
                    self.data.current_gen = max(self.data.past_gens) + 1
            else:
                self.data.current_gen = await self.next_gen()
        await self.next_pkmn()

    async def curr_pkmn(self):
        """This method is called when the cog has been reloaded, and the `active_votes` attribute is empty. It pulls any
        active votes from the vote table, or if none are active, generates the next votes.
        """
        if len(self.active_pokemon) != 0:
            return
        records = await self.db.fetch(
            """
            SELECT c.* FROM pokemon_tourney.combatant c 
            WHERE c.tourney_id = $1 AND c.end_time > $2 ORDER BY dex_no;
        """,
            self.data.id,
            datetime.utcnow(),
        )
        if len(records) == 0:
            await self.progress_tourney()
        else:
            for r in records:
                pkmn = CombatantData(
                    id=r.get("id"),
                    end_time=r.get("end_time"),
                    dex_no=r.get("dex_no"),
                    message=r.get("message_id"),
                    tourney=self.data,
                )
                self.active_pokemon.append(pkmn)

    async def next_pkmn(self):
        """This method progresses to the next set of Pokemon in the progression of the generation order,
        and changes the `active_votes` attribute of the tourney. If active votes is empty, it populates
        it with the initial votes.

        This method always assumes that the current generation has been set.
        """
        client = ClientSession()
        # Setting the generation if it hasn't been set yet.
        gen_response = await (
            await client.get(
                f"https://pokeapi.co/api/v2/generation/{self.data.current_gen}/"
            )
        ).json()
        # getting the first pokemon of the generation.
        next_pkmn = await (
            await client.get(gen_response["pokemon_species"][0]["url"])
        ).json()
        # clearing out the list of active pokemon if they're there.
        if len(self.active_pokemon) != 0:
            self.active_pokemon.clear()
        dex_no = next_pkmn["id"]
        prev_names = []
        now = datetime.utcnow()
        # We have at least 10 active votes per session.
        while True:
            # TODO add in logic for dealing with running into the next generation of pokemon.
            # adding the "next" (last) pokemon to the list.
            pkmn = CombatantData(
                id=uuid4(),
                end_time=now + self.data.interval,
                dex_no=dex_no,
                tourney=self.data,
            )
            self.active_pokemon.append(pkmn)
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
                or len(self.active_pokemon) < 12
            ):
                break
        for pkmn in self.active_pokemon:
            await pkmn.db_insert(self.db)
            view = CombatantView(bot=self.bot, c_data=pkmn)
            await view.start()
            self.bot.add_view(view)
        await client.close()

    async def next_gen(self) -> int:
        # TODO
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

    async def load_tourneys(self):
        records = await self.db.fetch("""select * from pokemon_tourney.data;""")
        for r in records:
            t_data = TourneyData(
                id=r.get("id"),
                channel=discord.Object(r.get("channel_id")),
                guild=discord.Object(r.get("guild_id")),
                interval=r.get("time_interval"),
                start_time=r.get("start_time"),
                current_gen=r.get("current_gen"),
                past_gens=r.get("past_gens"),
                vote_on_gen=r.get("vote_on_gen"),
                active=r.get("active"),
            )
            tourney = Tourney(t_data, self.bot)
            await tourney.curr_pkmn()
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

    @tasks.loop(minutes=15)
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
