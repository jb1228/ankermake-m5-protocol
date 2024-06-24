import json
from types import UnionType
from datetime import datetime
from dataclasses import dataclass, MISSING
from libflagship.util import unhex, enhex


class Serialize:

    @staticmethod
    def _safe_hash(obj):
        h = 0
        if isinstance(obj, list):
            for e in obj:
                h ^= Serialize._safe_hash(e)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                h ^= Serialize._safe_hash(k)
                h ^= Serialize._safe_hash(v)
        elif hasattr(obj, "__dataclass_fields__"):
            return Serialize.__hash__(obj)
        else:
            h ^= hash(obj)
        return h

    def __hash__(self):
        h = 0
        for name in self.__dataclass_fields__:
            field = getattr(self, name)
            h ^= self._safe_hash(field)
        return h

    @classmethod
    def from_dict(cls, data):
        res = {}
        for k, v in cls.__dataclass_fields__.items():
            if (k not in data) and (v.default is not MISSING):
                # prevent KeyErrors if there is a default value
                res[k] = v.default
            else:
                res[k] = data[k]
            if v.type == bytes:
                res[k] = unhex(res[k])
            elif v.type == datetime:
                res[k] = datetime.fromtimestamp(res[k])
            elif isinstance(v.type, UnionType):
                if res[k] and v.type.__args__[0] == datetime:
                    res[k] = datetime.fromtimestamp(res[k])
        return cls(**res)

    @staticmethod
    def _to_dict(val, recursive):
        if isinstance(val, bytes):
            return enhex(val)
        elif isinstance(val, datetime):
            return val.timestamp()
        elif isinstance(val, Serialize) and recursive:
            return val.to_dict()
        elif isinstance(val, dict) and recursive:
            res = {}
            for k, v in val.items():
                res[k] = Serialize._to_dict(v, recursive)
            return res
        else:
            return val

    def to_dict(self, recursive=True):
        res = {}
        for k, v in self.__dataclass_fields__.items():
            res[k] = self._to_dict(getattr(self, k), recursive)
        return res

    @classmethod
    def from_json(cls, data):
        return cls.from_dict(json.loads(data))

    def to_json(self):
        return json.dumps(self.to_dict())


@dataclass
class Printer(Serialize):
    id: str
    sn: str
    name: str
    model: str
    create_time: datetime
    update_time: datetime
    wifi_mac: str
    ip_addr: str
    mqtt_key: bytes
    api_hosts: str
    p2p_hosts: str
    p2p_duid: str
    p2p_key: str


@dataclass
class Account(Serialize):
    auth_token: str
    region: str
    user_id: str
    email: str
    country: str=""

    @property
    def mqtt_username(self):
        return f"eufy_{self.user_id}"

    @property
    def mqtt_password(self):
        return self.email


@dataclass
class Config(Serialize):
    account: Account
    printers: list[Printer]

    def __bool__(self):
        return bool(self.account)
