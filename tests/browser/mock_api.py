# A stand-in for the Brewbench API with made-up numbers, for browser tests of the website.
import json, http.server, random, math
from urllib.parse import urlparse, parse_qs
random.seed(4)
B=[("Tam, the Possibility","UG"),("Sigarda, Font of Blessings","GW"),("Rofellos, Llanowar Emissary","G"),("Zimone, Paradox Sculptor","UG"),("Kaalia of the Vast","WBR"),("Teval, the Balanced Scale","BGU"),("Atraxa, Grand Unifier","WUBG"),("Lathril, Blade of the Elves","BG"),("Dwalin, Weaponmaster","WR"),("Ajani Resolute","W"),("Gisa and Geralf","UB"),("Storm, Windrider","UR")]
S=[("R","R"),("UB","UB"),("WU","WU"),("BG","BG"),("RW","RW"),("UR","UR"),("WB","WB"),("G","G"),("BR","BR"),("WG","WG")]
def wil(w,n,z=1.96):
    p=w/n;d=1+z*z/n;c=(p+z*z/(2*n))/d;h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d;return [c-h,c+h]
def meta(f):
    src=B if f.endswith('brawl') else S
    tot=0;out=[]
    for i,(d,c) in enumerate(src):
        g=int(1800/(i+1.3)); wr=0.585-i*0.008+random.uniform(-.01,.01); w=int(g*wr); tot+=g
        sg=random.choice([0,4000,12000,25000]); sw=wr+random.uniform(-.03,.03)
        out.append({"deck":d,"colours":c,"real":{"games":g,"win_rate":w/g,"ci95":wil(w,g)},"sim":{"games":sg,"win_rate":sw} if sg else None})
    for o in out: o["share"]=o["real"]["games"]/tot
    return {"format":f,"since":"2026-10-17","real_games":tot,"decks":out}
def lb(f):
    names=["Player G","Player K","roodolpha","Player D","Player F","Player A","Player B","Player C","Player I","Player H","Player J","Player E"]
    src=B if f.endswith('brawl') else S; out=[]
    for i,n in enumerate(names):
        g=random.randint(60,420); wr=0.64-i*0.012; w=int(g*wr); d=src[i%len(src)]
        out.append({"pos":i+1,"name":n,"main_deck":d[0],"colours":d[1],"win_rate":w/g,"ci95":wil(w,g),"games":g})
    return {"min_rank":"Platinum","min_games":50,"players":out}
def mx(f):
    src=(B if f.endswith('brawl') else S)[:7]; d=[x[0] for x in src]
    grid=[[{"sim":{"win_rate":0.5+((i-j)*0.035)+random.uniform(-.04,.04),"games":800},"real":{"win_rate":0.5+random.uniform(-.1,.1),"games":40}} for j in range(len(d))] for i in range(len(d))]
    return {"decks":d,"grid":grid}
def player(n):
    return {"name":n,"games":278,"win_rate":0.534,"weeks":[{"week":f"2026-W{37+i}","win_rate":0.47+0.02*i+random.uniform(-.04,.04),"games":30+i*3} for i in range(9)],
     "decks":[{"format":"brawl","commander":"Zimone, Paradox Sculptor","colours":"UG","games":231,"win_rate":0.55,"first":"2026-09-02","last":"2026-11-15"},{"format":"brawl","commander":"Atraxa, Grand Unifier","colours":"WUBG","games":47,"win_rate":0.45,"first":"2026-08-10","last":"2026-09-01"}],
     "opponents":[{"opponent":x[0],"games":random.randint(6,25),"win_rate":random.uniform(.3,.7)} for x in B[:8]]}
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        u=urlparse(self.path); q=parse_qs(u.query); f=q.get("format",["brawl"])[0]
        p=u.path
        b = meta(f) if p=="/v1/meta" else lb(f) if p=="/v1/leaderboard" else mx(f) if p=="/v1/matchups" else player(p.split("/")[-1]) if p.startswith("/v1/players/") else {}
        self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers(); self.wfile.write(json.dumps(b).encode())
    def log_message(self,*a): pass
if __name__ == "__main__":
    import sys
    http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8796), H).serve_forever()
