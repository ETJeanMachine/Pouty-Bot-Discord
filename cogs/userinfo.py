from discord.ext import commands
from discord import Member, Embed, Role, utils
import time


class Userinfo:
    def __init__(self, bot):
        self.bot = bot

    @commands.command(pass_context=True)
    async def userinfo(self,ctx, member: Member=None):
        if member is None:
            member = ctx.message.author
        join_date = member.joined_at
        created_at = member.created_at
        user_color = member.color
        server = ctx.message.server
        if member.nick:
            nick = member.nick
        else:
            nick = member.name
        time_fmt = "%d %b %Y %H:%M"
        joined_number_of_days_diff = int((time.time() - time.mktime(join_date.timetuple())) // (3600 * 24))
        created_number_of_days_diff = int((time.time() - time.mktime(created_at.timetuple())) // (3600 * 24))
        embed = Embed(description="[{0.name}#{0.discriminator} - {1}]({2})".format(member, nick, member.avatar_url), color=user_color)
        if member.avatar_url:
            embed.set_thumbnail(url=member.avatar_url)
        else:
            embed.set_thumbnail(url=member.default_avatar_url)
        embed.add_field(name="Joined Discord on",
                        value="{}\n({} days ago)".format(member.created_at.strftime(time_fmt),
                                                        created_number_of_days_diff),
                        inline=True)
        embed.add_field(name="Joined Server on",
                        value="{}\n({} days ago)".format(member.joined_at.strftime(time_fmt),
                                                        joined_number_of_days_diff),
                        inline=True)

        member.roles.pop(0)
        member_number = sorted(server.members, key=lambda m: m.joined_at).index(member) + 1

        if member.roles:
            embed.add_field(name="Roles", value=", ".join([x.name for x in member.roles]), inline=True)
        embed.set_footer(text="Member #{} | User ID: {}".format(member_number, member.id))
        await self.bot.say(embed=embed)


def setup(bot):
    bot.add_cog(Userinfo(bot=bot))
