from killthebeast import Egg, ABRAnt, Queen


class Simplequeen(Queen):
    def layeggs(self):
        yield Egg(5,
                  larv=ABRAnt,
                  name="TTL 720p VC1 CLEAR",
                  server="playready.directtaps.net",
                  manifestpath="/smoothstreaming/TTLSS720VC1/To_The_Limit_720.ism/Manifest",
                  strategy=min)