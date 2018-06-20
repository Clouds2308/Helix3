import asyncio
import discord
from discord.ext import commands
import random
import youtube_dl
import code.get as get
import re
import aiohttp
import pprint
import logging
import numpy
import cv2
import math
import functools
from base64 import b16encode
import urllib.request
from code import bot
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)
# bot._setup_logging(log)

if not discord.opus.is_loaded():
    discord.opus.load_opus('opus')


class VoiceEntry:
    def __init__(self, message, player, song):
        self.requester = message.author
        self.channel = message.channel
        self.player = player
        self.song = song

    def __str__(self):
        fmt = '**{}** from **{}**\n{}'
        duration = self.player.duration
        return fmt.format(self.song.title, self.requester, self.song.thumbnail)


class Song:
    def __init__(self, url, title, channel, server, author,
                 file=None, thumbnail=None, player=None, webURL=None, length=None, msg=None):
        self.url = url  # url of the video itself
        self.webURL = webURL  # url of the youtube page
        self.length = length  # length of the video
        self.title = title  # title of the video
        self.channel = channel  # channel command was used in
        self.server = server  # server command was used in
        self.invoker = author  # person who asked for the song
        self.file = file  # cache file, not used rn
        self.thumbnail = thumbnail  # thumbnail of the video
        self.player = player  # the audio player itself (the thing that streams music from youtube to discord)
        self.npmessage = msg

class VoiceState:
    def __init__(self, bot):
        self.current = None
        self.voice = None
        self.bot = bot
        self.server = None
        self.play_next_song = asyncio.Event()
        self.songs = asyncio.Queue()
        self.skip_votes = set() # a set of user_ids that voted
        self.audio_player = self.bot.loop.create_task(self.audio_player_task())
        self.autoplaylist = open("autoplaylist.txt", "r")
        self.opts = {
            'format': 'bestaudio/best',
            'extractaudio': True,
            'audioformat': 'mp3',
            'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
            'restrictfilenames': True,
            'noplaylist': False,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'logtostderr': False,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'auto',
            'source_address': '0.0.0.0'
        }

    def is_playing(self):
        if self.voice is None or self.current is None:
            return False

        player = self.current.player
        return not player.is_done()

    @property
    def player(self):
        return self.current.player

    def skip(self):
        self.skip_votes.clear()
        if self.is_playing():
            self.player.stop()

    def toggle_next(self):
        self.bot.loop.call_soon_threadsafe(self.play_next_song.set)

    async def audio_player_task(self):
        while True:

            self.play_next_song.clear()
            try:
                self.current = await self.songs.get()
                try:
                    player = await self.voice.create_ytdl_player(self.current.url, ytdl_options=self.opts,
                                                                  after=self.toggle_next)
                    self.current.player = player
                except Exception as e:
                    fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'
                    await self.bot.send_message(self.current.channel, fmt.format(type(e).__name__, e))
                    log.error("Error in addsong:\n{}".format(fmt.format(type(e).__name__, e)))
                    return
                player.start()
                await self.announceNowPlaying()
                await self.play_next_song.wait()
            except:
                log.error("This should never happen, somehow the audio task has failed")

    async def announceNowPlaying(self):
        song = self.current
        log.debug("Playing {} in {}".format(song.title, song.server))
        em = discord.Embed(description="Playing **{}** from **{}**".format(song.title, song.invoker),
                           colour=(random.randint(0, 16777215)))
        em.set_image(url=song.thumbnail)

        await self.bot.send_message(self.current.channel, embed=em)

    async def getColour(self, url):
        def getImage(url):
            return urllib.request.urlretrieve(URL, filename)

        def floor(x):
            return int(x)

        # saves image (somehow doesnt work nested into `.imread()`
        filename = getImage(url)
        # gets img
        img = cv2.imread(filename)
        # avg color in one row
        avgColorRow = numpy.mean(img, axis=0)
        # averaging it for the whole image (saved in arr)
        avgColorRGBArr = numpy.mean(avgColorRow, axis=0)
        # turning it into a triplet
        avgColorRGB = (floor(avgColorRGBArr[0]), floor(avgColorRGBArr[1]), floor(avgColorRGBArr[2]))
        # convert RGB to hex
        avgColor = b16encode(bytes(avgColorRGB)).decode("utf-8")
        return avgColor


class Music:
    """Voice related commands.
    Works in multiple servers at once.
    """
    def __init__(self, bot, perms):
        self.bot = bot
        self.voice_states = {}
        self.perms = perms
        self.opts = {
            'format': 'bestaudio/best',
            'extractaudio': True,
            'audioformat': 'mp3',
            'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
            'restrictfilenames': True,
            'noplaylist': False,
            'nocheckcertificate': True,
            'ignoreerrors': False,
            'logtostderr': False,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'auto',
            'source_address': '0.0.0.0'
        }
        self.thread_pool = ThreadPoolExecutor(max_workers=2)

    def get_voice_state(self, server):
        """"Gets the current voice state for a specified server"""
        state = self.voice_states.get(server.id)
        if state is None:
            state = VoiceState(self.bot)
            self.voice_states[server.id] = state

        return state

    async def create_voice_client(self, channel):
        voice = await self.bot.join_voice_channel(channel)
        state = self.get_voice_state(channel.server)
        state.voice = voice

    def __unload(self):
        """Called when the cog is unloaded"""
        for state in self.voice_states.values():
            try:
                state.audio_player.cancel()
                if state.voice:
                    self.bot.loop.create_task(state.voice.disconnect())
            except:
                pass

    @commands.command(pass_context=True, no_pm=True)
    async def spawn(self, ctx):
        """Summons the bot to join your voice channel."""
        summoned_channel = ctx.message.author.voice_channel
        if summoned_channel is None:
            await self.bot.say('You are not in a voice channel.')
            return False
        msg = await self.bot.say('Joining... ``{}``'.format(summoned_channel.name))
        state = self.get_voice_state(ctx.message.server)
        if state.voice is None:
            state.voice = await self.bot.join_voice_channel(summoned_channel)
            await self.bot.edit_message(msg, 'Joined... ``{}``'.format(summoned_channel.name))
            log.info('Joined "{}"|"{}"'.format(ctx.message.server, summoned_channel))
        else:
            await state.voice.move_to(summoned_channel)
            await self.bot.edit_message(msg, 'Moved to... ``{}``'.format(summoned_channel.name))
            log.info('{} moved me to {}'.format(ctx.message.author, summoned_channel.name))

        return True

    async def addsong(self, songData, ctx, playlist=False):
        state = self.get_voice_state(songData.server)
        # await self.create_voice_client(ctx.message.author.voice_channel)
        try:
            await self.bot.edit_message(songData.npmessage, 'Added ' + songData.title)
        except:
            songData.npmessage = await self.bot.send_message(songData.channel, 'Added ' + songData.title)
        await state.songs.put(songData)
        log.debug("{} was added to the {}'s queue by {}".format(songData.title,
                                                                songData.server.name,
                                                                songData.invoker.name))
    @commands.command(pass_context=True, no_pm=True)
    async def play(self, ctx, *, song:str):
        """Plays a song.
        If there is a song currently in the queue, then it is
        queued until the next song is done playing.
        This command automatically searches as well from YouTube.
        The list of supported sites can be found here:
        https://rg3.github.io/youtube-dl/supportedsites.html
        """
        state = self.get_voice_state(ctx.message.server)
        ytdl = youtube_dl.YoutubeDL(self.opts)

        if state.voice is None:
            success = await ctx.invoke(self.spawn)
            if not success:
                return
        msg = await self.bot.say("Processing... :confused:")
        regex = re.compile(
            r'^(?:http|ftp)s?://'
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
            r'(?:/?|[/?]\S+)$)', re.IGNORECASE)
        if not re.match(regex, ctx.message.content.split(" ")[1]):
            info = ytdl.extract_info(url=song, download=False, process=True)
            for item in info['entries']:
                song = Song(url=item['url'], title=item['title'], channel=ctx.message.channel, server=ctx.message.server, author=ctx.message.author, thumbnail=item['thumbnail'], msg=msg)
                await self.addsong(song, ctx)
        else:
            song = ctx.message.content.split(" ")[1]
            if "playlist" in song:
                info = ytdl.extract_info(url=song, download=False, process=False)
                items = await self.async_process_youtube_playlist(playlist_url=song, channel=ctx.message.channel, author=ctx.message.author, msg=msg, ytdl=ytdl, ctx=ctx)
            else:
                await self.addsong(songInfo, ctx)

    async def async_process_youtube_playlist(self, playlist_url, ytdl, ctx, msg, **meta):
        """
            Processes youtube playlists links from `playlist_url` in a questionable, async fashion.
            :param playlist_url: The playlist url to be cut into individual urls and added to the playlist
            :param meta: Any additional metadata to add to the playlist entry
            :param ytdl: Youtube_dl object created in .play
            :param ctx: context
        """
        info = False
        try:
            info = ytdl.extract_info(url=playlist_url, download=False, process=False)
        except Exception as e:
            log.error('Could not extract information from {}\n\n{}'.format(playlist_url, e))
            return
        if not info:
            log.error('Could not extract information from %s' % playlist_url)
            return
        for entry_data in info['entries']:
            if entry_data:
                baseurl = info['webpage_url'].split('playlist?list=')[0]
                song_url = baseurl + 'watch?v=%s' % entry_data['id']
                data = await self.extract_info(url=song_url, download=False, process=True)
                song = Song(url=data['url'], title=data['title'], channel=ctx.message.channel,
                            server=ctx.message.server, author=ctx.message.author, thumbnail=data['thumbnail'], msg=msg)
                await self.addsong(song, ctx, playlist=True)

    async def extract_info(self, *args, **kwargs):
        """
            Runs ytdl.extract_info within a threadpool to avoid blocking the bot's loop
        """
        loop = self.bot.loop
        ytdl = youtube_dl.YoutubeDL(self.opts)
        return await loop.run_in_executor(self.thread_pool, functools.partial(ytdl.extract_info, *args, **kwargs))

    @commands.command(pass_context=True, no_pm=True)
    async def volume(self, ctx):
        """Sets the volume of the currently playing song."""
        state = self.get_voice_state(ctx.message.server)
        player = state.player

        value = ctx.message.content.strip()
        value = value.split(" ")
        if len(value) == 1:
            await self.bot.say("Im playing at ``{:.0%}`` volume".format(player.volume))
        else:

            try:
                value = int(value[1])
            except:

                # if value[0][0] in '+-':
                #     new_volume = value[0]
                #     new_volume += (player.volume * 100)
                #     if 0 < new_volume <= 100:
                #         player.volume = new_volume / 100.0
                # else:
                await self.bot.say("Thats not a number now is it, {}".format(ctx.message.author.display_name))
                return
            if value > 100:
                await self.bot.say("no")
                return
            if state.is_playing():

                player.volume = value / 100
                await self.bot.say('Set the volume to {:.0%}'.format(player.volume))

    @commands.command(pass_context=True, no_pm=True)
    async def pause(self, ctx):
        """Pauses the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.pause()
            await self.bot.say(":pause_button: ")
        else:
            await self.bot.say("But im not playing anything Dx")

    @commands.command(pass_context=True, no_pm=True)
    async def resume(self, ctx):
        """Resumes the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.resume()
            await self.bot.say(":arrow_forward:")
        else:
            await self.bot.say("But im not playing anything Dx")

    @commands.command(pass_context=True, no_pm=True)
    async def stop(self, ctx):
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """
        server = ctx.message.server
        state = self.get_voice_state(server)

        if state.is_playing():
            player = state.player
            player.stop()
            await self.bot.say(":stop_button:")

        try:
            state.audio_player.cancel()
            del self.voice_states[server.id]
            await state.voice.disconnect()
        except:
            pass

    @commands.command(pass_context=True, no_pm=True)
    async def skip(self, ctx):
        """Vote to skip a song. The song requester can automatically skip.
        skip votes are needed for the song to be skipped.
        """
        state = self.get_voice_state(ctx.message.server)
        if not state.is_playing():
            await self.bot.say('But im not playing anything ;-;')
            return
        voter = ctx.message.author
        if voter.id in ['174918559539920897']: # placeholder dev override until perms system finished
            await self.bot.say('``Dev Override``:track_next:')
            state.skip()
        elif voter == state.current.requester:
            await self.bot.say(':track_next:')
            state.skip()
        elif voter.id not in state.skip_votes:
            numInChannel = sum(1 for m in state.voice.channel.voice_members if not(
                m.deaf or m.self_deaf or m.bot
            ))
            required_votes = math.floor(0.5 * numInChannel)
            state.skip_votes.add(voter.id)
            total_votes = len(state.skip_votes)
            if total_votes >= required_votes:
                await self.bot.say(':track_next:')
                state.skip()
            else:
                await self.bot.say('Skip vote: [{}/{}]'.format(total_votes, required_votes))
        else:
            await self.bot.say('Now now, you cant vote twice :P')

    @commands.command(pass_context=True, no_pm=True)
    async def np(self, ctx):
        """Shows info about the currently played song."""

        state = self.get_voice_state(ctx.message.server)
        if state.current is None:
            await self.bot.say('Not playing anything.')
        else:
            thumbnail = state.player.url
            thumbnail = thumbnail.replace("www.", "")
            thumbnail = thumbnail.replace("https://youtube.com/watch?v=", "http://img.youtube.com/vi/")
            thumbnail = thumbnail + "/mqdefault.jpg"
            em = discord.Embed(description="**{}**",
                               colour=(random.randint(0, 16777215)))
            em.set_footer(text=state.player.url)
            em.set_image(url=thumbnail)
            await self.bot.send_message(ctx.message.channel, embed=em)