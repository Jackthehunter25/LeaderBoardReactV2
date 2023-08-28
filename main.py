import json

import discord
from discord.ext import commands
from dispie import Paginator
from pymongo import MongoClient

intents = discord.Intents.all()
intents.reactions = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

####################CONFIG####################################################
TOKEN = 'MTE0Mzk4MjI2MzUwMDAyNTkwNw.GF7VGw.lJqu3Wzo_snfd7at-2_WbVdNmubx2L8gVuPLRQ'
num_user_per_leaderboard_page = 10
# MongoDB URI
mongo_uri = "mongodb+srv://barron123:barron123@cluster0.4omprhh.mongodb.net/?retryWrites=true&w=majority"
####################CONFIG####################################################

# Initialize MongoDB client and database
mongo_client = MongoClient(mongo_uri)
mongo_db = mongo_client["Leaderboard"]

monitored_channels_collection = mongo_db["monitored_channels"]
reaction_data_collection = mongo_db["reaction_data"]


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')


@bot.event
async def on_raw_reaction_add(payload):
    if not (await bot.fetch_user(payload.user_id)).bot:
        channel_id = payload.channel_id

        monitored_channel = monitored_channels_collection.find_one({"channel_id": channel_id})
        if monitored_channel:
            message = await bot.get_channel(channel_id).fetch_message(payload.message_id)
            author_id = message.author.id
            emoji = str(payload.emoji.name)  # or payload.emoji.id if custom emoji

            # Update reaction data in MongoDB
            reaction_data_collection.update_one(
                {"channel_id": channel_id, "author_id": author_id},
                {"$inc": {f"reactions.{emoji}": 1}},
                upsert=True
            )

@bot.event
async def on_raw_reaction_remove(payload):
    if not (await bot.fetch_user(payload.user_id)).bot:
        channel_id = payload.channel_id

        monitored_channel = monitored_channels_collection.find_one({"channel_id": channel_id})
        if monitored_channel:
            message = await bot.get_channel(channel_id).fetch_message(payload.message_id)
            author_id = message.author.id
            emoji = str(payload.emoji.name)  # or payload.emoji.id if custom emoji

            # Decrease reaction count in MongoDB
            reaction_data_collection.update_one(
                {"channel_id": channel_id, "author_id": author_id, f"reactions.{emoji}": {"$gt": 0}},
                {"$inc": {f"reactions.{emoji}": -1}}
            )


@bot.command()
@commands.has_permissions(administrator=True)
async def update(ctx, channel: discord.TextChannel):
    monitored_channel = monitored_channels_collection.find_one({"channel_id": channel.id})
    if not monitored_channel:
        await ctx.send("This channel is not being monitored. Use `!monitor <channel>` to start monitoring.")
        return

    author_reaction_map = {}  # Store author IDs and their reactions

    messages = []
    async for message in channel.history(limit=None):
        messages.append(message)

    for message in messages:
        author_id = message.author.id
        if author_id not in author_reaction_map:
            author_reaction_map[author_id] = {}  # Initialize reactions for the author

        for reaction in message.reactions:
            async for user in reaction.users():
                if not user.bot:
                    emoji = str(reaction.emoji)

                    # Update reaction data for the author in the map
                    author_reaction_map[author_id][emoji] = author_reaction_map[author_id].get(emoji, 0) + 1

    # Update reaction data in MongoDB for each author
    for author_id, reactions in author_reaction_map.items():
        reaction_data_collection.update_one(
            {"channel_id": channel.id, "author_id": author_id},
            {"$inc": {"reactions": reactions}},
            upsert=True
        )

    await ctx.send(f"Updated reaction data for {len(messages)} messages in {channel.mention}.")

@commands.has_permissions(administrator=True)
@bot.command()
async def monitor(ctx, channel: discord.TextChannel):
    monitored_channel = monitored_channels_collection.find_one({"channel_id": channel.id})
    if monitored_channel:
        await ctx.send("This channel is already being monitored.")
    else:
        monitored_channels_collection.insert_one({"channel_id": channel.id})
        await ctx.send(f"Started monitoring {channel.mention} for reactions.")

@bot.command()
@commands.has_permissions(administrator=True)
async def unmonitor(ctx, channel: discord.TextChannel):
    monitored_channel = monitored_channels_collection.find_one({"channel_id": channel.id})
    if monitored_channel:
        monitored_channels_collection.delete_one({"channel_id": channel.id})
        await ctx.send(f"Stopped monitoring {channel.mention} for reactions.")
    else:
        await ctx.send("This channel was not being monitored.")

@bot.command()
async def leaderboard(ctx, channel: discord.TextChannel = None):
    if channel:
        index = 0
        channel_id = channel.id
        monitored_channel = monitored_channels_collection.find_one({"channel_id": channel_id})
        if not monitored_channel:
            await ctx.send("The provided channel is not being monitored for reactions.")
            return

        users_reaction_data = reaction_data_collection.find({"channel_id": channel_id})
        user_reactions = {}

        for user_reaction_data in users_reaction_data:
            user_id = user_reaction_data["author_id"]
            reactions = user_reaction_data["reactions"]
            user_reactions[user_id] = reactions

        pages = []

        for user_id, reactions in user_reactions.items():
            user = ctx.guild.get_member(user_id)
            if user:
                total_reactions = sum(reactions.values())
                top_reactions = sorted(reactions, key=reactions.get, reverse=True)[:3]
                top_reactions_str = " | ".join([f"{emoji} x {reactions[emoji]}" for emoji in top_reactions])
                user_info = f"Total Reactions: {total_reactions}\nTop Reactions: {top_reactions_str}"
                index += 1
                if index == 1:
                    user_embed = discord.Embed(title=f"Leaderboard for {channel.mention}:", description=f"{user.mention}\n{user_info}")
                else:
                    user_embed = discord.Embed(description=f"{user.mention}\n{user_info}")
                pages.append(user_embed)

        paginator = Paginator(pages, per_page=num_user_per_leaderboard_page)  # Show 1 user per page
        await paginator.start(ctx)

    else:
        users_reaction_data = reaction_data_collection.find()
        user_reactions = {}  # Store reactions for each user

        for user_reaction_data in users_reaction_data:
            user_id = user_reaction_data["author_id"]
            reactions = user_reaction_data["reactions"]

            # Aggregate reactions for each user
            if user_id not in user_reactions:
                user_reactions[user_id] = reactions
            else:
                for emoji, count in reactions.items():
                    user_reactions[user_id][emoji] = user_reactions[user_id].get(emoji, 0) + count

        top_users = sorted(user_reactions, key=lambda user: sum(user_reactions[user].values()), reverse=True)[:num_user_per_leaderboard_page]
        pages = []

        for user_id in top_users:
            user = ctx.guild.get_member(user_id)
            if user:
                reactions = user_reactions[user_id]
                total_reactions = sum(reactions.values())
                top_reactions = sorted(reactions, key=reactions.get, reverse=True)[:3]
                top_reactions_info = " | ".join([f"{emoji} x {reactions[emoji]}" for emoji in top_reactions])
                user_info = f"Total Reactions: {total_reactions}\nTop Reactions: {top_reactions_info}"

                user_embed = discord.Embed(title=f"Combined Leaderboard", description=f"{user.mention}\n{user_info}")
                pages.append(user_embed)

        paginator = Paginator(pages, per_page=1)  # Show 1 user per page
        await paginator.start(ctx)

@bot.command()
async def help(ctx):
    help_embed = discord.Embed(title="Bot Commands", description="Here are the available commands:")
    help_embed.add_field(name="!monitor <channel>", value="Start monitoring a channel for reactions.", inline=False)
    help_embed.add_field(name="!unmonitor <channel>", value="Stop monitoring a channel for reactions.", inline=False)
    help_embed.add_field(name="!leaderboard [channel]", value="Show the reaction leaderboard for a specific channel.", inline=False)
    help_embed.add_field(name="!leaderboard", value="Show the combined reaction leaderboard.", inline=False)
    help_embed.add_field(name="!help", value="Display this help message.", inline=False)
    await ctx.send(embed=help_embed)

bot.run(TOKEN)
