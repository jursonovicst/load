from threading import Thread, Event
import sched
import time
from ants import Msg
import pycurl
from typing import Callable
import random  # this is needed, because the strategy function may be a random function.
from manifestparser import MParser


class Ant(Thread):
    """
    An ant template, does not do anything.
    """

    def __init__(self, **kw):
        """
        An ant does regular work. You may overload this method to initialize stuff for your Ant.
        :param kw: keyword arguments passed to the Thread class
        """
        super(Ant, self).__init__(**kw)

        # Ant's scheduler to start tasks.
        self._scheduler = sched.scheduler(time.time, time.sleep)

        # connection for remote logging
        self._conn = None

        self._stopevent = Event()

    def schedulework(self, delay, *args):
        """
        Schedule work for the ant.
        :param delay: Time at work should be done
        :param args: Arguments passed to the work() method.
        """
        self._scheduler.enter(delay=delay, priority=100, action=self.work, argument=args)

    def run(self):
        """
        Do not overload this function, overload work() instead.
        """

        assert self._conn is not None, "I need a valid connection to send log messages..."
        self._log("born")

        # process tasks, this will block till end of simulation or till interrupt.
        self._scheduler.run()

        # clean up stuff, if any
        try:
            self.cleanup()
        except BaseException as e:
            self._log("cleanup error: '%s'" % str(e))

        self._log("died")

    def work(self, *args):
        """
        Overload this to define your work.
        :param args: optional arguments for your implementation.
        """
        pass

    def cleanup(self):
        """
        Called after finished processing the tasks to clean up stuff. You may overload this method.
        """
        pass

    def terminate(self):
        self._stopevent.set()

    @property
    def conn(self):
        return self._conn

    @conn.setter
    def conn(self, conn):
        self._conn = conn

    def _log(self, msg):
        self._conn.send(Msg("%s '%s': %s" % (self.__class__.__name__, self.name, msg)))


class SleepyAnt(Ant):
    """
    An example Ant implementation for sleeping for a bit.
    """

    def __init__(self, sleepperiod: int, **kw):
        super(SleepyAnt, self).__init__(**kw)
        if sleepperiod < 0:
            raise ValueError("sleepperiod must be non negative: %d" % sleepperiod)

        self.schedulework(sleepperiod)

    def work(self, *args):
        self._log("waken up")


class HTTPAnt(Ant):
    """
    An example Ant implementation for accessing a list of HTTP URLs.
    """

    def __init__(self, server: str, paths, delays, host: str = None, **kw):
        super(HTTPAnt, self).__init__(**kw)
        if len(paths) != len(delays):
            raise ValueError("length mismatch: %d vs. %d" % (len(paths), len(delays)))

        self._server = server

        self._curl = pycurl.Curl()
        self._curl.setopt(pycurl.WRITEFUNCTION, lambda x: None)
        if host is not None:
            self._curl.setopt(pycurl.HTTPHEADER, ['Host: %s' % host])

        # schedule work
        for path, delay in zip(paths, delays):
            self.schedulework(delay, path)

    def work(self, *args):
        path = args[0]
        url = "http://%s%s" % (self._server, path)

        self._curl.setopt(pycurl.URL, url)
        self._curl.perform()

        self._log("'%s': %s" % (url, self._curl.getinfo(pycurl.HTTP_CODE)))

    def cleanup(self):
        self._curl.close()


class ABRAnt(Ant):
    """
    An Example ABR streaming Ant implementation, it will open an ABR stream, and download streaming fragments.
    """

    def __init__(self, server: str, manifestpath, strategy, duration=0, host: str = None, **kw):
        """
        :param server: IP address or host name of the streaming server.
        :param manifestpath: Path of the manifest to open.
        :param strategy: Bitrate switching strategy, the given function shall return one value of the bitrates, which
        will be handed over as a list of integers in the first argument.
        :param duration: Limit streaming by duration sec.
        :param host: HTTP host header to be sent (may be needed, if server is specified by IP address).
        :param kw: Any additional parameter to be handed over to its parent class (and eventually to the Thread class).
        """
        assert isinstance(strategy, Callable), "Strategy must be callable: '%s'" % strategy
        super(ABRAnt, self).__init__(**kw)

        self._host = host

        self._videocurl = pycurl.Curl()
        self._audiocurl = pycurl.Curl()
        self._videocurl.setopt(pycurl.WRITEFUNCTION, lambda x: None)
        self._audiocurl.setopt(pycurl.WRITEFUNCTION, lambda x: None)

        if self._host is not None:
            self._videocurl.setopt(pycurl.HTTPHEADER, ['Host: %s' % self._host])
            self._audiocurl.setopt(pycurl.HTTPHEADER, ['Host: %s' % self._host])

        mparser = MParser("http://%s%s" % (server, manifestpath))

        for at, path, ranges in mparser.fragments(MParser.VIDEO, strategy=strategy, duration=duration):
            self.schedulework(at,
                              self._videocurl,
                              server,
                              path,
                              ranges)

        for at, path, ranges in mparser.fragments(MParser.AUDIO, strategy=strategy, duration=duration):
            self.schedulework(at,
                              self._audiocurl,
                              server,
                              path,
                              ranges)

        # manifestcurl = pycurl.Curl()
        #
        # if host is not None:
        #     manifestcurl.setopt(pycurl.HTTPHEADER, ['Host: %s' % host])
        #
        # try:
        #     manifestcurl.setopt(pycurl.URL, "http://%s%s" % (server, manifestpath))
        #     response = BytesIO()
        #     manifestcurl.setopt(pycurl.WRITEDATA, response)
        #     manifestcurl.perform()
        #
        #     if int(manifestcurl.getinfo(pycurl.HTTP_CODE)) != 200:
        #         raise Exception(
        #             "cannot load %s, return code: %d" % (manifestcurl.geturl(), manifestcurl.getinfo(pycurl.HTTP_CODE)))
        #
        #     manifestcurl.close()
        #
        #     # parse XML and fuck Microsoft!
        #     charset = chardet.detect(response.getvalue())['encoding']
        #     manifest = response.getvalue().decode(charset).encode(charset)
        #     root = etree.fromstring(manifest)
        #
        #     # validate manifest
        #     assert root.tag == 'SmoothStreamingMedia', "Invalid root tag: '%s'" % root.tag
        #     assert root.get('MajorVersion') == '2', "Invalid Major version: '%s'" % root.get('MajorVersion')
        #     assert root.get('IsLive', default="false") != "true", "Live manifests are not supported"
        #
        #     # get TimeScale
        #     timescale = root.get('TimeScale', default='10000000')
        #
        #     # get the StreamIndex for video
        #     streamindex = root.find("StreamIndex[@Type='video']")
        #     if streamindex is not None:
        #         # get the video bitrates
        #         bitrates = list(map(lambda element: int(element.get('Bitrate')), streamindex.findall('QualityLevel')))
        #         assert len(bitrates) == int(streamindex.get('QualityLevels')), "invalid bitrate count"
        #
        #         # get TimeScale
        #         videotimescale = int(streamindex.get('TimeScale', default=timescale))
        #
        #         # get the fragment url part
        #         urltemplate = streamindex.get('Url')
        #         assert urltemplate is not None, "empty urltemplate"
        #
        #         # get event times
        #         ds = list(map(lambda ee: int(ee.get('d')), streamindex.findall("c")))
        #         # add first fragment's timestamp
        #         ds.insert(int(streamindex.find('c').get('t', default='0')), 0)
        #         # duration of last fragment is not needed
        #         del ds[-1]
        #         assert len(ds) == int(streamindex.get('Chunks')), "fragment number mismatch: %d vs. %d" % (
        #             len(ds), int(streamindex.get('Chunks')))
        #
        #         for cd in np.cumsum(ds):
        #             self.schedulework(float(cd) / videotimescale,
        #                               self._videocurl,
        #                               server,
        #                               os.path.dirname(manifestpath) + "/" + urltemplate.replace(
        #                                   '{start time}', str(cd)).replace(
        #                                   '{bitrate}', str(strategy(bitrates)))
        #                               )
        #
        #     # get the StreamIndex for audio
        #     streamindex = root.find("StreamIndex[@Type='audio']")
        #     if streamindex is not None:
        #         # get the video bitrates
        #         bitrates = list(map(lambda element: int(element.get('Bitrate')), streamindex.findall('QualityLevel')))
        #         assert len(bitrates) != 0, "Empty bitrates"
        #
        #         # get TimeScale
        #         audiotimescale = int(streamindex.get('TimeScale', default=timescale))
        #
        #         # get the fragment url part
        #         urltemplate = streamindex.get('Url')
        #         assert urltemplate is not None, "empty urltemplate"
        #
        #         # get event times
        #         ds = list(map(lambda ee: int(ee.get('d')), streamindex.findall("c")))
        #         # add first fragment's timestamp
        #         ds.insert(int(streamindex.find('c').get('t', default='0')), 0)
        #         # duration of last fragment is not needed
        #         del ds[-1]
        #         assert len(ds) == int(streamindex.get('Chunks')), "fragment number mismatch: %d vs. %d" % (
        #             len(ds), int(streamindex.get('Chunks')))
        #
        #         for cd in np.cumsum(ds):
        #             self.schedulework(float(cd) / audiotimescale,
        #                               self._audiocurl,
        #                               server,
        #                               os.path.dirname(manifestpath) + "/" + urltemplate.replace(
        #                                   '{start time}', str(cd)).replace(
        #                                   '{bitrate}', str(strategy(bitrates)))
        #                               )
        #     manifestcurl.close()
        #
        # except pycurl.error as err:
        #     raise Exception("Cannot load %s, error message: %s" % ("http://%s%s" % (server, manifestpath), err))
        #
        # self._videocurl = pycurl.Curl()
        # self._audiocurl = pycurl.Curl()
        # self._videocurl.setopt(pycurl.WRITEFUNCTION, lambda x: None)
        # self._audiocurl.setopt(pycurl.WRITEFUNCTION, lambda x: None)

    def work(self, *args):
        assert 3 <= len(args) <= 5
        curl = args[0]
        server = args[1]
        path = args[2]
        rfrom, rto = args[3] if len(args) == 4 else (None, None)

        curl.setopt(pycurl.URL, "http://%s%s" % (server, path))
        if rfrom is not None:
            curl.setopt(pycurl.RANGE, "%s-%s" % (rfrom, rto if rto is not None else ""))
        curl.perform()

    def cleanup(self):
        self._videocurl.close()
        self._audiocurl.close()
