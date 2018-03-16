import discord
from discord.ext import commands
import os.path
import json
class Admin:
    def __init__(self, bot):
        self.bot = bot
        if os.path.exists('data/report_channel.json'):
            with open('data/report_channel.json') as f:
                json_data = json.load(f)
                self.report_channel = self.bot.get_channel(json_data['channel'])
        else:
            self.report_channel = None


    @commands.group(pass_context=True)
    async def report(self, ctx, message: str, reported_user: discord.User=None, channel: discord.Channel=None):
        """
        usage:
        !report "report reason" reported_user [name/id] (optional) channel_id [name/id] (optional)

        don't forget the quotes around the reason, optionally you can attach a screenshot via file upload

        examples:
        !report "I was meanly bullied by <user>" 123456789 0987654321
        !report "I was bullied by <user>"
        !report "I was bullied by <user>" User_Name general
        """
        if message == 'setup':
            await ctx.invoke(self.setup, ctx=ctx)
            return
        if not self.report_channel:
            await self.bot.say("report channel not set up yet, message a moderator")
            return
        report_message = "**Report Message:**\n{}\n".format(message)

        if reported_user:
            report_message += "**Reported User:**\n{}\n".format(reported_user.mention)
        if channel:
            report_message +="**Channel:**\n{}\n".format(channel.mention)
        if ctx.message.attachments:
            report_message += "**Included Screenshot:**\n{}\n".format(ctx.message.attachments[0]['url'])

        await self.bot.send_message(self.report_channel, report_message)



    @report.command(name="setup")
    async def setup(self, ctx):
        """
        use '[.,!]report setup' in the channel that should become the report channel
        """
        self.report_channel = ctx.message.channel
        with open('data/report_channel.json' , 'w') as f:
            json.dump({"channel" : self.report_channel.id}, f)
        await self.bot.say('This channel is now the report channel')


def setup(bot):
    bot.add_cog(Admin(bot))
