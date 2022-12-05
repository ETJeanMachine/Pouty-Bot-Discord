import discord
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
class TourneyData:
    id: UUID
    channel: Union[int, discord.TextChannel, discord.VoiceChannel]
    guild: Union[int, discord.Guild]
    time_interval: timedelta
    generation_order: List[str]

    def available_options(used_vals=[]) -> List[discord.SelectOption]:
        generations = [
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
        options = []
        for val in generations:
            if val not in used_vals:
                label = val.replace("-", " ").replace("g", "G")
                label = label[0:10] + label[10:].upper()
                options.append(discord.SelectOption(label=label, value=val))
        return options


@dataclass
class VoteData:
    vote_id: UUID
    votes: List[int]
    start_time: datetime
    dex_no: int
    tourney_id: TourneyData


class TourneyStartView(discord.ui.View):
    def __init__(self, *, tourney: TourneyData, bot: commands.Bot):
        super().__init__(timeout=None)
        self.tourney = tourney
        self.bot = bot
        self.initial_votes: List[VoteData] = []

    @discord.ui.select(placeholder="Pick a Generation!", options=TourneyData.available_options())
    async def gen_select(self, inter: discord.Interaction, select: discord.ui.Select):
        self.tourney.generation_order.append(select.values[0])
        if(len(self.tourney.generation_order) < 9):
            select.options = TourneyData.available_options(self.tourney.generation_order)
        else:
            select.disabled = True
        self.remove_gen_button.disabled = False
        if len(self.tourney.generation_order) == 9:
            self.start_button.disabled = False
        else:
            self.start_button.disabled = True
        await inter.response.edit_message(embed=self.embed, view=self)

    @discord.ui.button(label="Remove Last Gen", disabled=True, emoji="➖")
    async def remove_gen_button(
        self, inter: discord.Interaction, btn: discord.ui.Button
    ):
        self.tourney.generation_order.pop()
        self.gen_select.disabled = False
        self.start_button.disabled = True
        self.gen_select.options = TourneyData.available_options(self.tourney.generation_order)
        await inter.response.edit_message(embed=self.embed, view=self)
        if len(self.tourney.generation_order) == 0:
            btn.disabled = True
            self.start_button.disabled = False

    @discord.ui.button(label="Start Tourney", disabled=False, emoji="▶️")
    async def start_button(self, inter: discord.Interaction, btn: discord.ui.Button):
        pass

    @property
    def embed(self):
        embed = discord.Embed(
            title="Start Pokemon Tourney",
            description="This is an interactive menu for starting a Pokemon tourney and setting the order of generations for the Tourney. If no generations are selected, it defaults to 1-9.",
        )
        for idx, gen in enumerate(self.tourney.generation_order):
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
        self.open_votes: List[VoteData] = []

    async def cog_load(self):
        await self.init_db()
        await self.load_votes()

    async def load_votes(self):
        pass

    async def populate_db(self):

        results = await self.bot.db.fetch(
            """
            SELECT pokedex.dex_no
            FROM pokemon.pokedex pokedex;
        """
        )
        session = ClientSession()
        response = await session.get("https://pokeapi.co/api/v2/pokedex/national")
        session.close()
        data: Dict[str, Any] = await response.json()
        pokedex = data["pokemon_entries"]
        if len(pokedex) > len(results):
            for i in range(len(pokedex) - len(results)):
                species = pokedex[i]["pokemon_species"]
                insert = f"""
                    INSERT INTO pokemon.pokedex(dex_no, name, url)
                    VALUES({pokedex[i]["entry_number"]}, '{species["name"]}', '{species["url"]}');
                """
                await self.bot.db.execute(insert)

    async def init_db(self):
        query = """
            CREATE SCHEMA IF NOT EXISTS pokemon;
            CREATE TABLE IF NOT EXISTS pokemon.tourney(
                tourney UUID PRIMARY KEY,
                channel BIGINT,
                guild_id BIGINT,
                generation_order TEXT ARRAY,
                time_interval INTERVAL
            );
            CREATE TABLE IF NOT EXISTS pokemon.vote(
                vote_id UUID PRIMARY KEY,
                votes JSONB,
                end_time TIMESTAMP WITH TIME ZONE,
                dex_no INT,
                tourney_id UUID REFERENCES pokemon.tourney (tourney_id) ON DELETE CASCADE
            );
        """
        await self.bot.db.execute(query)
        # await self.populate_db()

    pokemon = app_commands.Group(
        name="pokemon", description="Commands for ranking Pokemon."
    )

    @pokemon.command(name="start")
    async def pokemon_start(
        self,
        interaction: discord.Interaction,
        channel: Union[discord.TextChannel, discord.VoiceChannel],
        interval: app_commands.Transform[
            Optional[timedelta], TimeDeltaTransformer
        ] = None,
    ):
        """Generates a new tourney for ranking Pokemon.

        Args:
            interaction (discord.Interaction): The discord interaction for this app command.
            channel (discord.TextChannel): The channel to send the tourney messages in.
            interval (app_commands.Transform[ Optional[timedelta], TimeDeltaTransformer ], optional): The length of time, in hours, between batches of votes. Defaults to 24 if not provided.
        """
        if interval == None:
            interval = timedelta(hours=24)

        tourney_data = TourneyData(
            id=uuid4(),
            channel=channel,
            guild=interaction.guild,
            time_interval=interval,
            generation_order=[],
        )
        start_view = TourneyStartView(bot=self.bot, tourney=tourney_data)
        await start_view.start(interaction=interaction)
        await start_view.wait()
        self.open_votes = start_view.initial_votes


async def setup(bot: commands.Bot):
    await bot.add_cog(Pokemon(bot))
