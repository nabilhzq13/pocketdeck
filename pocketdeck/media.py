"""Now playing (title / artist / album art) from Windows' media sessions – Spotify, browsers,
Media Player, etc. Runs on the asyncio loop. Everything degrades to None if WinRT is missing."""
import hashlib
import logging

log = logging.getLogger("pocketdeck.media")

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager)
    from winrt.windows.storage.streams import Buffer, DataReader, InputStreamOptions
except Exception as e:  # pragma: no cover
    SessionManager = None
    log.info("Now playing unavailable: %s", e)


class NowPlaying:
    def __init__(self):
        self.manager = None
        self.art = {}          # hash -> (bytes, content type)
        self._art_key = None
        self._art_hash = None
        self.available = SessionManager is not None

    async def _session(self):
        if not self.available:
            return None
        if self.manager is None:
            self.manager = await SessionManager.request_async()
        return self.manager.get_current_session()

    async def read(self):
        try:
            s = await self._session()
            if s is None:
                return None
            props = await s.try_get_media_properties_async()
            info = s.get_playback_info()
            status = int(info.playback_status) if info else 0
            title = props.title or ""
            artist = props.artist or props.album_artist or ""
            if not title and not artist:
                return None
            data = {"title": title, "artist": artist, "album": props.album_title or "",
                    "playing": status == 4, "app": _app_name(s.source_app_user_model_id),
                    "art": None}
            key = (title, artist, props.album_title)
            if key != self._art_key:
                self._art_key, self._art_hash = key, await self._read_art(props.thumbnail)
            data["art"] = self._art_hash
            return data
        except Exception as e:
            log.debug("media read failed: %s", e)
            self.manager = None
            return None

    async def _read_art(self, thumb):
        if thumb is None:
            return None
        try:
            stream = await thumb.open_read_async()
            size = int(stream.size)
            if not size or size > 8_000_000:
                return None
            buf = Buffer(size)
            await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
            reader = DataReader.from_buffer(buf)
            raw = bytearray(buf.length)
            reader.read_bytes(raw)
            raw = bytes(raw)
            ctype = "image/png" if raw[:4] == b"\x89PNG" else "image/jpeg"
            h = hashlib.sha1(raw).hexdigest()[:16]
            self.art = {h: (raw, ctype)}   # keep only the current cover
            return h
        except Exception as e:
            log.debug("album art failed: %s", e)
            return None

    async def control(self, cmd):
        """Returns True if handled through the media session, False to fall back to media keys."""
        try:
            s = await self._session()
            if s is None:
                return False
            fn = {"playpause": s.try_toggle_play_pause_async, "next": s.try_skip_next_async,
                  "prev": s.try_skip_previous_async, "stop": s.try_stop_async}.get(cmd)
            return bool(fn and await fn())
        except Exception:
            self.manager = None
            return False


def _app_name(aumid):
    if not aumid:
        return ""
    low = aumid.lower()
    for key, name in (("spotify", "Spotify"), ("chrome", "Chrome"), ("msedge", "Edge"),
                      ("firefox", "Firefox"), ("zen", "Zen"), ("zunemusic", "Media Player"),
                      ("vlc", "VLC"), ("discord", "Discord"), ("itunes", "iTunes")):
        if key in low:
            return name
    return aumid.split("!")[-1].split("\\")[-1].removesuffix(".exe")
