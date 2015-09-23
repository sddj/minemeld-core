"""
Simple segment tree implementation based on LevelDB.

**KEYS**

Numbers are 8-bit unsigned.

- Segment key: (1, <start>, <end>, <level>, <uuid>)
- Endpoint key: (1, <endpoint>, <type>, <level>, <uuid>)

**ENDPOINT**

- Type: 0: START, 1: END
"""

import plyvel
import struct
import logging
import shutil

LOG = logging.getLogger(__name__)

MAX_LEVEL = 0xFE
TYPE_START = 0x00
TYPE_END = 0x1


class ST(object):
    def __init__(self, name, epsize, truncate=False):
        if truncate:
            try:
                shutil.rmtree(name)
            except:
                pass

        self.db = plyvel.DB(
            name,
            create_if_missing=True,
            bloom_filter_bits=10,
            write_buffer_size=24*1024
        )
        self.epsize = epsize
        self.max_endpoint = (1 << epsize)

    def _split_interval(self, start, end, lower, upper):
        if start <= lower and upper <= end:
            return [(lower, upper)]

        mid = (lower+upper)/2

        result = []
        if start <= mid:
            result += self._split_interval(start, end, lower, mid)
        if end > mid:
            result += self._split_interval(start, end, mid+1, upper)

        return result

    def _segment_key(self, start, end, uuid_=None, level=None):
        res = struct.pack(">BQQ", 1, start, end)
        if level is not None:
            res += struct.pack("B", level)
            if uuid_ is not None:
                res += uuid_
        return res

    def _split_segment_key(self, key):
        _, start, end, level = struct.unpack(">BQQB", key[:18])
        return start, end, level, key[18:]

    def _endpoint_key(self, endpoint, level=None, type_=None, uuid_=None):
        res = struct.pack(">BQ", 2, endpoint)
        if level is not None:
            res += struct.pack("B", level)
            if type_ is not None:
                res += struct.pack("B", type_)
                if uuid_ is not None:
                    res += uuid_
        return res

    def _split_endpoint_key(self, k):
        _, endpoint, level, type_ = struct.unpack(">BQBB", k[:11])
        type_ = (True if type_ == TYPE_START else False)
        return endpoint, level, type_, k[11:]

    def close(self):
        self.db.close()

    def put(self, uuid_, start, end, level=0):
        si = self._split_interval(start, end, 0, self.max_endpoint)
        value = struct.pack(">QQ", start, end)

        batch = self.db.write_batch()

        for i in si:
            k = self._segment_key(i[0], i[1], uuid_=uuid_, level=level)
            batch.put(k, value)

        ks = self._endpoint_key(
            start,
            level=level,
            type_=TYPE_START,
            uuid_=uuid_
        )
        batch.put(ks, "\x00")
        ke = self._endpoint_key(
            end,
            level=level,
            type_=TYPE_END,
            uuid_=uuid_
        )
        batch.put(ke, "\x00")

        batch.write()

    def delete(self, uuid_, start, end, level=0):
        batch = self.db.write_batch()

        si = self._split_interval(start, end, 0, self.max_endpoint)
        for i in si:
            k = self._segment_key(i[0], i[1], uuid_=uuid_, level=level)
            batch.delete(k)

        ks = self._endpoint_key(
            start,
            level=level,
            type_=TYPE_START,
            uuid_=uuid_
        )
        batch.delete(ks)
        ke = self._endpoint_key(
            end,
            level=level,
            type_=TYPE_END,
            uuid_=uuid_
        )
        batch.delete(ke)

        batch.write()

    def cover(self, value):
        lower = 0
        upper = self.max_endpoint*2

        while True:
            mid = (lower+upper)/2
            if value <= mid:
                upper = mid
            else:
                lower = mid+1

            ks = self._segment_key(lower, upper)
            ke = self._segment_key(lower, upper, level=MAX_LEVEL+1)

            for k, v in self.db.iterator(start=ks, stop=ke, include_value=True,
                                         reverse=True, include_start=False,
                                         include_stop=False):
                _, _, level, uuid_ = self._split_segment_key(k)
                start, end = struct.unpack(">QQ", v)

                yield uuid_, level, start, end

            if lower == upper:
                break

    def query_endpoints(self, start=None, stop=None, reverse=False,
                        include_start=True, include_stop=True):
        if start is None:
            start = self._endpoint_key(0)
        else:
            start = self._endpoint_key(start)
        if stop is None:
            stop = self._endpoint_key(self.max_endpoint, level=MAX_LEVEL+1)
        else:
            stop = self._endpoint_key(stop, level=MAX_LEVEL+1)

        di = self.db.iterator(
            start=start,
            stop=stop,
            reverse=reverse,
            include_value=False,
            include_start=include_start,
            include_stop=include_stop
        )
        for k in di:
            yield self._split_endpoint_key(k)
