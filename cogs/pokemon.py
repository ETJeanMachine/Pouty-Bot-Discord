import discord
import asyncpg
from aiohttp import ClientSession
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from discord.ext import commands
from discord import app_commands
from typing import Dict, Any, List, Optional, Union
from uuid import UUID, uuid4


class TimeDeltaTransformer(app_commands.Transformer):
    @classmethod
    async def transform(
        cls, interaction: discord.Interaction, argument: int
    ) -> timedelta:
        delta = timedelta(hours=int(argument))
        return delta


@dataclass
class VoteData:
    id: UUID
    votes: List[int]
    end_time: datetime
    dex_no: str

    @classmethod
    def _finish(cls):
        cls.tourney: TourneyData
        del cls._finish

    async def create_in_store(self, db: Union[asyncpg.Connection, asyncpg.Pool]):
        await db.execute(
            """
            INSERT INTO pokemon.vote VALUES ($1, $2, $3, $4, $5);
        """,
            self.id,
            self.votes,
            self.end_time,
            self.dex_no,
            self.tourney.id,
        )


@dataclass
class TourneyData:
    id: UUID
    channel: Union[int, discord.TextChannel, discord.VoiceChannel]
    guild: Union[int, discord.Guild]
    gen_order: List[str]
    interval: timedelta
    active_votes: List[VoteData]
    _generations = [
        "generation-i",
        "generation-ii",
        "generation-iii",
        "generation-iv",
        "generation-v",
        "generation-vi",
        "generation-vii",
        "generation-viii",
        "generation-ix",
    ]

    @classmethod
    def available_options(cls, used_vals=[]) -> List[discord.SelectOption]:
        options = []
        for val in cls._generations:
            if val not in used_vals:
                label = val.replace("-", " ").replace("g", "G")
                label = label[0:10] + label[10:].upper()
                options.append(discord.SelectOption(label=label, value=val))
        return options

    async def create_in_store(self, db: Union[asyncpg.Connection, asyncpg.Pool]):
        await db.execute(
            """
            INSERT INTO pokemon.tourney VALUES ($1, $2, $3, $4, $5);
        """,
            self.id,
            self.channel.id,
            self.guild.id,
            self.gen_order,
            self.interval,
        )

    async def current_votes(self, db: Union[asyncpg.Connection, asyncpg.Pool]) -> None:
        """This method is called when the cog has been reloaded, and the `active_votes` attribute is empty. It pulls any
        active votes from the vote table, or if none are active, generates the next votes.

        Args:
            db (Union[asyncpg.Connection, asyncpg.Pool]): The database that this method pulls from.
        """
        if len(self.active_votes) != 0:
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
                self.active_votes.append(vote)

    async def next_votes(self, db: Union[asyncpg.Connection, asyncpg.Pool]):
        """This method progresses to the next set of Pokemon in the progression of the generation order,
        and changes the `active_votes` attribute. If active votes is empty, it populates it with the initial votes.

        Args:
            db (Union[asyncpg.Connection, asyncpg.Pool]): The database that this method pulls from.
        """
        client = ClientSession()
        next_pkmn = None
        current_gen = self.gen_order[0]
        # called when starting a new tourney.
        if len(self.active_votes) == 0:
            gen_response = await (
                await client.get(f"https://pokeapi.co/api/v2/generation/{current_gen}/")
            ).json()
            # getting the first pokemon of the generation.
            next_pkmn = await (
                await client.get(gen_response["pokemon_species"][0]["url"])
            ).json()
        else:
            next_pkmn = await (
                await client.get(self.active_votes[len(self.active_votes) - 1])
            ).json()
            if next_pkmn["generation"]["name"] != current_gen:
                current_gen = next_pkmn["generation"]["name"]
            self.active_votes.clear()
        dex_no = next_pkmn["id"]
        prev_names = []
        # We have at least 10 active votes per session.
        while True:
            # adding the "next" (last) pokemon to the list.
            vote = VoteData(
                id=uuid4(),
                votes=[0, 0, 0, 0, 0, 0],
                end_time=datetime.now() + self.interval,
                dex_no=dex_no,
            )
            vote.tourney = self
            self.active_votes.append(vote)
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
                or len(self.active_votes) < 10
            ):
                break
        for vote in self.active_votes:
            await vote.create_in_store(db)
        await client.close()


VoteData._finish()


class TourneyStartView(discord.ui.View):
    def __init__(self, *, tourney: TourneyData, bot: commands.Bot):
        super().__init__(timeout=None)
        self.tourney = tourney
        self.bot = bot
        self.initial_votes: List[VoteData] = []

    @discord.ui.select(
        placeholder="Pick a Generation!", options=TourneyData.available_options()
    )
    async def gen_select(self, inter: discord.Interaction, select: discord.ui.Select):
        self.tourney.gen_order.append(select.values[0])
        if len(self.tourney.gen_order) < 9:
            select.options = TourneyData.available_options(self.tourney.gen_order)
        else:
            select.disabled = True
        self.remove_gen_button.disabled = False
        if len(self.tourney.gen_order) == 9:
            self.start_button.disabled = False
        else:
            self.start_button.disabled = True
        await inter.response.edit_message(embed=self.embed, view=self)

    @discord.ui.button(label="Remove Last Gen", disabled=True, emoji="➖")
    async def remove_gen_button(
        self, inter: discord.Interaction, btn: discord.ui.Button
    ):
        self.tourney.gen_order.pop()
        self.gen_select.disabled = False
        self.start_button.disabled = True
        self.gen_select.options = TourneyData.available_options(self.tourney.gen_order)
        await inter.response.edit_message(embed=self.embed, view=self)
        if len(self.tourney.gen_order) == 0:
            btn.disabled = True
            self.start_button.disabled = False

    @discord.ui.button(label="Start Tourney", disabled=False, emoji="▶️")
    async def start_button(self, inter: discord.Interaction, btn: discord.ui.Button):
        if len(self.tourney.gen_order) == 0:
            for gen in TourneyData._generations:
                self.tourney.gen_order.append(gen)
        await self.tourney.create_in_store(self.bot.db)
        await self.tourney.next_votes(self.bot.db)
        await inter.response.edit_message(
            content="Tourney successfully generated!", embed=None, view=None
        )

    @property
    def embed(self):
        embed = discord.Embed(
            title="Start Pokemon Tourney",
            description="This is an interactive menu for starting a Pokemon tourney and setting the order of generations for the Tourney. If no generations are selected, it defaults to 1-9.",
        )
        for idx, gen in enumerate(self.tourney.gen_order):
            label = gen.replace("-", " ").replace("g", "G")
            label = label[0:10] + label[10:].upper()
            embed.add_field(name=idx + 1, value=label, inline=False)
        return embed

    async def start(self, interaction: discord.Interaction):
        self.interaction = interaction
        await interaction.response.send_message(
            embed=self.embed, view=self, ephemeral=True
        )
        self.message = await interaction.original_response()


class Pokemon(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db: Union[asyncpg.Connection, asyncpg.Pool] = bot.db
        self.active_tourneys: List[TourneyData] = []

    async def load_tourneys(self):
        records = await self.db.fetch(
            """
            SELECT t.* FROM pokemon.tourney t;
        """
        )
        for r in records:
            tourney = TourneyData(
                id=r.get("id"),
                channel=discord.Object(r.get("channel")),
                guild=discord.Object(r.get("guild")),
                gen_order=r.get("gen_order"),
                interval=r.get("time_interval"),
                active_votes=[],
            )
            await tourney.current_votes(self.db)
            self.active_tourneys.append(tourney)

    async def init_db(self):
        query = """
            CREATE SCHEMA IF NOT EXISTS pokemon;
            CREATE TABLE IF NOT EXISTS pokemon.tourney(
                id UUID PRIMARY KEY,
                channel BIGINT,
                guild_id BIGINT,
                gen_order TEXT ARRAY,
                time_interval INTERVAL
            );
            CREATE TABLE IF NOT EXISTS pokemon.vote(
                id UUID PRIMARY KEY,
                votes INT ARRAY,
                end_time TIMESTAMP WITH TIME ZONE,
                dex_no INT,
                tourney_id UUID REFERENCES pokemon.tourney (id) ON DELETE CASCADE
            );
        """
        await self.db.execute(query)

    async def cog_load(self):
        await self.init_db()
        await self.load_tourneys()

    pokemon = app_commands.Group(
        name="pokemon", description="Commands for ranking Pokemon."
    )

    @pokemon.command(name="start")
    @app_commands.checks.has_permissions(administrator=True)
    async def pokemon_start(
        self,
        interaction: discord.Interaction,
        channel: Union[discord.TextChannel, discord.VoiceChannel],
        interval: app_commands.Transform[
            Optional[timedelta], TimeDeltaTransformer
        ] = None,
    ):
        """Generates a new tourney for ranking Pokemon. Admin-only command.

        Args:
            interaction (discord.Interaction): The discord interaction for this app command.
            channel (discord.TextChannel): The channel to send the tourney messages in.
            interval (app_commands.Transform[ Optional[timedelta], TimeDeltaTransformer ], optional): The length of
            time, in hours, between batches of votes. Defaults to 24 if not provided.
        """
        # First checking if there is an active tourney in this guild. If there is, we must throw an exception.
        records = await self.db.fetch(
            """
            SELECT * FROM pokemon.tourney WHERE guild = $1;
        """,
            interaction.guild.id,
        )
        if len(records) != 0:
            raise app_commands.AppCommandError(
                "Tourney already started in guild, stop tourney to begin a new one."
            )
        if interval == None:
            interval = timedelta(hours=24)

        tourney_data = TourneyData(
            id=uuid4(),
            channel=channel,
            guild=interaction.guild,
            interval=interval,
            gen_order=[],
            active_votes=[],
        )
        start_view = TourneyStartView(bot=self.bot, tourney=tourney_data)
        await start_view.start(interaction=interaction)
        await start_view.wait()
        self.active_tourneys.append(start_view.tourney)


async def setup(bot: commands.Bot):
    await bot.add_cog(Pokemon(bot))
