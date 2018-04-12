import aiohttp
from discord.ext import commands
import json
from bs4 import BeautifulSoup
from urllib import parse
from urllib import request


class Wolfram:
    """Wolfram Alpha related commands"""

    def __init__(self, bot):
        self.bot = bot
        self.json_file = 'data/wolfram.json'
        self.session = aiohttp.ClientSession()

    @commands.command()
    async def wolfram(self, *, query: str):
        """
        gives a wolfram query result
        :param query: the query you want to search use 'image' as first keywoard to get your result as image
        """
        with open(self.json_file) as f:
            api_key = json.load(f)['api_key']

        url = 'http://api.wolframalpha.com/v2/query'
        want_image = query.split(' ')[0] == 'image'
        if not want_image:
            params = {'appid': api_key, 'input': query, 'format': 'plaintext'}
            await self.bot.type()
            async with self.session.get(url=url, params=params) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    success = soup.find('queryresult')['success']
                    if success == 'true':
                        query_input = soup.find('plaintext').contents
                        full_response = '<http://www.wolframalpha.com/input/?i={}>'.format(parse.quote_plus(query))
                        message = '**Full Response:** {} \n'.format(full_response)
                        message += '**Input:** {} \n'.format(query_input[0])
                        message += '**Result:** \n' \
                                   '```\n'
                        for elem in soup.find_all('plaintext')[1:6]:
                            if len(elem) > 0:
                                message += elem.contents[0] + '\n'
                        message += '```'

                        await self.bot.say(message)
                    else:
                        await self.bot.say('Query was unsuccessful please try something else')
        else:
            re_query = query.split(' ')[1:]
            re_query = ' '.join(re_query)
            params = {'appid': api_key, 'input': re_query, 'format': 'plaintext,image'}
            await self.bot.type()
            async with self.session.get(url=url, params=params) as response:
                if response.status == 200:
                    soup = BeautifulSoup(await response.text(), 'html.parser')
                    success = soup.find('queryresult')['success']
                    if success == 'true':
                        query_input = soup.find('plaintext').contents
                        full_response = 'http://www.wolframalpha.com/input/?i={}'.format(parse.quote_plus(re_query))
                        message = '**Full Response:** {} \n'.format(full_response)
                        message += '**Input:** {} \n'.format(query_input[0])
                        message += '**Result:** \n'
                        await self.bot.say(message)
                        for elem in soup.find_all('img')[1:5]:
                            await self.bot.upload(request.urlopen(elem['src']),filename='wolfram.png')
                    else:
                        await self.bot.say('Query was unsuccessful please try something else')

    def __unload(self):
        self.session.close()


def setup(bot):
    bot.add_cog(Wolfram(bot))
