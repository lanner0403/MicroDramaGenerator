"""重寫內建短劇：每篇 ≤180 秒，走到小高潮就停。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "preset_stories.json"


def shots(*rows):
    out = []
    t = 0
    for row in rows:
        plot, dlg = row[0], (row[1] if len(row) > 1 else "")
        dur = row[2] if len(row) > 2 else None
        if dur is None:
            raise ValueError("shot missing duration")
        item = {"start": t, "end": t + dur, "plot": plot, "camera": "static"}
        if dlg:
            item["dialogue"] = dlg
        out.append(item)
        t += dur
    return out, t


def beat(title, extra, plot, rows, **kw):
    sh, total = shots(*rows)
    d = {
        "title": title,
        "tags": kw.pop("tags", "1girl, 1boy, fully clothed"),
        "extra": extra,
        "plot": plot,
        "duration": total,
        "nsfw": False,
        "shots": sh,
    }
    d.update(kw)
    if total < 5 or total > 12:
        raise ValueError(f"{title} duration {total} not in 5-12")
    return d


def pack(sid, title, summary, clothing, cast, fragments):
    total = sum(int(b["duration"]) for b in fragments)
    if total > 180:
        raise ValueError(f"{sid} total {total}s > 180")
    return sid, {
        "title": title,
        "summary": summary,
        "clothing": clothing,
        "cast": cast,
        "fragments": fragments,
    }


STORIES = {}

sid, body = pack(
    "flash_ceo",
    "閃婚老公是千億總裁",
    "民政局抓錯人閃婚，揭底千億總裁，飯局被羞辱後他當眾護妻——小高潮後即停。",
    "casual clothes, white blouse, high-waist skirt, everyday outfit",
    {"female": 1, "male": 1},
    [
        beat("被裁", "empty office at night, computer, cardboard box, indoor",
             "Alone in the office at night she packs a box after being fired.",
             [("Night office. The adult woman packs a cardboard box, tired, fully clothed.", "", 4),
              ("She stares at the empty desk, then picks up the box.", "明天…去民政局。", 4)],
             tags="1girl, office, packing, tired, indoor, solo", solo=True),
        beat("民政局排隊", "civil affairs office, waiting chairs, indoor, daylight",
             "She waits in the civil affairs office, looking for the stand-in husband.",
             [("Bright civil affairs office. She stands in line holding a folder, fully clothed.", "", 4),
              ("She looks around, anxious, searching for someone.", "人呢…", 4)],
             tags="1girl, standing, indoor, waiting, solo", solo=True),
        beat("抓錯袖子", "civil affairs office, indoor, daylight",
             "She grabs the sleeve of the wrong tall man in a black suit.",
             [("She turns and grabs a tall man in a black suit by the sleeve.", "就是你吧？快簽字。", 5),
              ("He looks down at her, calm, and does not pull away.", "", 5)],
             tags="1girl, 1boy, surprised, standing, indoor"),
        beat("蓋章成婚", "civil affairs counter, red stamp, indoor, daylight",
             "The red marriage stamp hits the papers.",
             [("They sit at the counter. A clerk holds a red stamp.", "", 4),
              ("The stamp slams down. He signs without hesitation.", "從今天起，你是我太太。", 5)],
             tags="1girl, 1boy, sitting, papers, indoor"),
        beat("走出大廳", "civil affairs lobby, glass doors, daylight",
             "They walk out together; she still thinks he is a stand-in.",
             [("They walk toward the glass doors. She hugs the folder.", "謝了。錢我之後轉。", 4),
              ("He glances at her, unreadable, and holds the door.", "", 4)],
             tags="1girl, 1boy, walking, indoor"),
        beat("車庫揭底", "underground parking, black luxury sedan, fluorescent light",
             "Black cars and bodyguards wait; she realizes he is not a stand-in.",
             [("Underground garage. A black sedan waits, door open.", "", 4),
              ("Two bodyguards bow. She freezes.", "這…你到底是誰？", 6)],
             tags="1girl, 1boy, shocked, parking garage"),
        beat("上車", "car interior, night, city lights through window",
             "In the car he tells her to go home with him.",
             [("Car interior. She sits stiffly. He loosens his tie.", "上車。回家再說。", 4),
              ("The car pulls out. She stares at the city lights.", "", 4)],
             tags="1girl, 1boy, sitting, car interior"),
        beat("總裁室", "CEO office, floor-to-ceiling glass, city skyline, daylight",
             "In the top-floor office she sees his name on the desk.",
             [("Vast CEO office. She stands small against the glass.", "", 4),
              ("She reads the nameplate, stunned.", "千億集團…是你？", 6)],
             tags="1girl, 1boy, office, shocked, indoor"),
        beat("她要走", "CEO office, doorway, city window, daylight",
             "She turns to leave; he does not raise his voice.",
             [("She picks up her bag and turns toward the door.", "這婚作廢。", 4),
              ("He remains seated, watching her, not moving yet.", "", 4)],
             tags="1girl, 1boy, turning away, office"),
        beat("他攔住", "CEO office, doorway, indoor, daylight",
             "He steps in front of the door and stops her.",
             [("He stands in the doorway, blocking her, still calm.", "證件上已經是真的。", 5),
              ("She looks up at him, trapped and angry.", "", 4)],
             tags="1girl, 1boy, doorway, confrontation"),
        beat("豪宅夜", "luxury penthouse entrance, chandelier, night, indoor",
             "They enter a penthouse. She looks out of place.",
             [("Penthouse entrance, chandelier. She steps in holding her box.", "", 4),
              ("He hangs his jacket. She stays by the door.", "我不住這。", 4)],
             tags="1girl, 1boy, indoor, night, luxury"),
        beat("飯局入座", "penthouse dining room, long table, chandelier, night",
             "Family dinner. Relatives already seated.",
             [("Long dining table, night city in the window. She sits beside him.", "", 4),
              ("An older relative looks her up and down.", "哪來的？", 4)],
             tags="1girl, 1boy, dinner, indoor, night"),
        beat("被羞辱", "penthouse dining room, long table, chandelier, night",
             "A relative calls her a gold-digger in front of everyone.",
             [("The relative points at her, sneering.", "她配得上這張桌子？", 5),
              ("She lowers her eyes. Fingers tighten on the napkin.", "", 5)],
             tags="1girl, 1boy, humiliation, dinner, indoor"),
        beat("小高潮護妻", "penthouse dining room, standing, chandelier, night",
             "He slams the table and shields her. This is the climax; the story stops after the next beat.",
             [("He puts down his chopsticks. The room goes still.", "", 4),
              ("He stands, hand on her chair, voice cold.", "再罵一句，這桌人今晚都出去。", 6)],
             tags="1girl, 1boy, standing, confrontation, indoor"),
        beat("收束", "penthouse dining room, chandelier, night, indoor",
             "Silence. He looks at her, not at them.",
             [("The table is silent. She looks up at him.", "", 4),
              ("He does not sit. He looks only at her.", "這婚，我認。", 6)],
             tags="1girl, 1boy, looking at each other, indoor, night"),
    ],
)
STORIES[sid] = body

sid, body = pack(
    "rebirth_slap",
    "重生當眾退婚",
    "訂婚當日重生，宴會上當眾退婚甩證據，真貴客起身認親——小高潮後離場即停。",
    "alternate costume, elegant evening dress, jewelry, formal",
    {"female": 1, "male": 2},
    [
        beat("驚醒", "hotel suite bedroom, white dress on rack, daylight, indoor",
             "She gasps awake on the morning of the engagement banquet.",
             [("Hotel suite. She sits up sharply, gasping.", "我…沒死？", 4),
              ("She looks at her hands, then at the dress on the rack.", "", 4)],
             tags="1girl, sitting up, shocked, indoor, solo", solo=True),
        beat("對鏡", "hotel suite vanity, large mirror, daylight, indoor",
             "She looks in the mirror; her expression turns cold.",
             [("Vanity mirror. She sits in a slip, staring at herself.", "", 4),
              ("A cold small smile. She stands.", "這一次，換我來。", 4)],
             tags="1girl, looking in mirror, indoor, solo", solo=True),
        beat("戴耳環", "hotel suite vanity, evening dress, jewelry, indoor",
             "She puts on earrings, ready for war.",
             [("She wears the evening dress, putting on an earring.", "", 4),
              ("She checks herself once, then walks out.", "", 4)],
             tags="1girl, evening dress, indoor, solo", solo=True),
        beat("走廊", "hotel corridor, carpet, wall lights, indoor",
             "She walks the hotel corridor toward the banquet.",
             [("Hotel corridor. She walks toward the camera, chin up.", "", 4),
              ("She does not hesitate at the corner.", "", 4)],
             tags="1girl, walking, corridor, evening dress, solo", solo=True),
        beat("宴會門外", "banquet hall doors, floral stand, evening, indoor",
             "Outside the hall she hears music and laughter.",
             [("Closed banquet doors. Music leaks out. She stops one second.", "", 4),
              ("She pushes the door open.", "", 4)],
             tags="1girl, doorway, evening dress, indoor, solo", solo=True),
        beat("進場", "luxury banquet hall, chandeliers, aisle, evening",
             "She walks the aisle. Guests turn.",
             [("Banquet hall, chandeliers. She walks the center aisle.", "", 5),
              ("Guests turn to look. She does not smile.", "", 5)],
             tags="1girl, walking, banquet, evening dress"),
        beat("台上", "banquet stage, floral arch, tuxedo, evening",
             "The fiancé on stage still smiles, expecting her to take his arm.",
             [("On stage a man in a tuxedo smiles, holding a glass.", "", 4),
              ("He reaches for her arm. She does not take it.", "", 4)],
             tags="1girl, 1boy, banquet stage, evening"),
        beat("拿麥", "banquet stage, microphone, floral arch, evening",
             "She takes the microphone from the stand.",
             [("She takes the mic. The hall quiets.", "", 4),
              ("The fiancé's smile thins.", "", 4)],
             tags="1girl, 1boy, microphone, banquet"),
        beat("當眾退婚", "banquet stage, microphone, shocked crowd, evening",
             "She publicly calls off the engagement.",
             [("She stands center stage, voice steady.", "這門婚事，我退了。", 6),
              ("His smile cracks. Glasses freeze in the air.", "", 4)],
             tags="1girl, 1boy, rejecting, banquet, indoor"),
        beat("甩證據", "banquet stage, phone screen glow, evening",
             "She holds up her phone with proof of the affair and stolen shares.",
             [("She holds up a glowing phone. He reaches; she steps aside.", "", 5),
              ("Guests stand.", "股票、出軌、錄音，都在這。", 5)],
             tags="1girl, 1boy, phone, shocked guests, banquet"),
        beat("全場炸", "banquet hall, guests standing, chandeliers, evening",
             "The hall erupts. The fiancé cannot speak.",
             [("Guests talking, standing. He is white-faced.", "", 4),
              ("She keeps the phone high, chin lifted.", "", 4)],
             tags="1girl, 1boy, crowd, banquet, indoor"),
        beat("小高潮認親", "banquet hall aisle, main table, evening, indoor",
             "A man at the main table stands, takes her hand, and claims the marriage.",
             [("A tall man in a dark suit stands at the main table.", "", 5),
              ("He walks on stage and takes her hand.", "這婚，我娶。", 7)],
             tags="1girl, 1boy, holding hands, banquet, indoor"),
        beat("牽手離場", "banquet hall aisle, chandeliers, guests parted, evening",
             "They walk out hand in hand. The story stops here.",
             [("They walk the aisle toward the camera, holding hands.", "", 5),
              ("She glances at him. He does not let go.", "走，這次換你跟我。", 5)],
             tags="1girl, 1boy, walking, holding hands, banquet"),
    ],
)
STORIES[sid] = body

sid, body = pack(
    "hidden_ice",
    "隱婚三年他先低頭",
    "隱婚三年冷得像合租，謠言把她逼到大廳，他當眾認妻後夜裡低頭——小高潮後回抱即停。",
    "alternate costume, office lady, white blouse, pencil skirt",
    {"female": 1, "male": 1},
    [
        beat("冰冷早餐", "modern apartment dining table, morning window, coffee, indoor",
             "They eat breakfast without looking at each other.",
             [("Morning apartment. They sit across a small table with coffee.", "", 4),
              ("He slides a plate. She does not meet his eyes.", "謝謝。我先出門。", 4)],
             tags="1girl, 1boy, breakfast, looking away, indoor"),
        beat("躲開", "apartment hallway, shoe cabinet, morning, indoor",
             "In the hallway he reaches for her bag; she steps aside.",
             [("Hallway. He reaches for her bag strap.", "", 4),
              ("She steps aside so his fingers miss.", "我自己可以。", 4)],
             tags="1girl, 1boy, hallway, avoiding touch, indoor"),
        beat("分頭出門", "apartment door, morning light, indoor",
             "She leaves first. He watches the door close.",
             [("She opens the door without looking back.", "", 4),
              ("He stands in the hall, hand still half-raised.", "", 4)],
             tags="1girl, 1boy, doorway, morning, indoor"),
        beat("公司進門", "corporate lobby, marble floor, glass doors, daylight",
             "They arrive at the same company as strangers.",
             [("Marble lobby. She badges in, eyes down.", "", 4),
              ("He enters behind her, no greeting.", "", 4)],
             tags="1girl, 1boy, lobby, office, daylight"),
        beat("會議裝不熟", "glass meeting room, long table, city window, daylight",
             "He is the CEO; she is a subordinate. They pretend not to know each other.",
             [("He sits at the head. She sits far away with a notebook.", "", 5),
              ("He asks a professional question. She answers without looking up.", "報告，數據我放桌上了。", 5)],
             tags="1girl, 1boy, meeting room, office, indoor"),
        beat("謠言", "office pantry, coffee machine, daylight, indoor",
             "In the pantry colleagues gossip that she is clinging to the CEO.",
             [("Two colleagues whisper. She stands in the doorway with a cup.", "她是不是攀上總裁了？", 5),
              ("The cup stops. Her face stays calm. She turns to leave.", "", 5)],
             tags="1girl, office pantry, hurt, indoor"),
        beat("她忍", "office corridor, indoor, daylight",
             "She walks the corridor, holding it in.",
             [("Office corridor. She walks, eyes forward, cup in hand.", "", 4),
              ("She does not look at anyone.", "", 4)],
             tags="1girl, walking, corridor, indoor, solo", solo=True),
        beat("擦肩", "office corridor, indoor, daylight",
             "They pass in the corridor. Neither stops.",
             [("They pass. His sleeve almost brushes hers.", "", 4),
              ("Neither turns around.", "", 4)],
             tags="1girl, 1boy, corridor, walking, indoor"),
        beat("大廳", "corporate lobby, marble, glass doors, daylight",
             "She walks toward the exit after work.",
             [("Lobby. She walks toward the glass doors, bag on her shoulder.", "", 4),
              ("He appears from the elevator, sees her.", "", 4)],
             tags="1girl, 1boy, lobby, walking, indoor"),
        beat("小高潮認妻", "corporate lobby, marble floor, reception, daylight",
             "He stops her, holds her wrist, and tells the floor she is his wife.",
             [("He steps in front of her and catches her wrist, not hard.", "", 5),
              ("Staff freeze. He looks at them, then at her.", "她是我太太。隱婚三年。", 7)],
             tags="1girl, 1boy, lobby, announcement, indoor"),
        beat("全場", "corporate lobby, shocked staff, daylight, indoor",
             "The lobby is silent. She stares at him.",
             [("Staff staring. She looks at him, eyes wide.", "", 4),
              ("He does not let go of her wrist.", "", 4)],
             tags="1girl, 1boy, lobby, shocked, indoor"),
        beat("夜裡沙發", "apartment living room, sofa, warm lamp, night, indoor",
             "At night on the sofa he sits at the far end, silent.",
             [("Warm lamp, night. She sits on the sofa looking at her hands.", "", 5),
              ("He sits at the other end, jacket off.", "", 5)],
             tags="1girl, 1boy, sofa, night, indoor"),
        beat("低頭", "apartment living room, sofa, warm lamp, night",
             "He slides closer, head bowed, and apologizes.",
             [("He slides closer, head bowed.", "是我先把你當空氣。對不起。", 6),
              ("She stares at him, not moving yet.", "", 4)],
             tags="1girl, 1boy, sofa, apology, indoor"),
        beat("回抱", "apartment living room, sofa, warm lamp, night",
             "She cries and hugs him. The story stops here.",
             [("She leans forward and wraps her arms around his shoulders.", "", 5),
              ("They hold each other. She speaks into his shirt.", "這次…不准再裝不熟。", 5)],
             tags="1girl, 1boy, hug, sofa, night, indoor"),
    ],
)
STORIES[sid] = body

sid, body = pack(
    "wall_gold",
    "牆裡的金塊",
    "老鼠站著告訴她牆裡有金塊。她跟房東續租，向五金行老闆買鎚子，槌開牆，金塊倒下來，她大笑發財了——小高潮後即停。",
    "casual clothes, t-shirt, long pants, everyday outfit",
    {"female": 1, "male": 2},
    [
        beat("老鼠報信", "old apartment living room, cracked plaster wall, afternoon, indoor",
             "A small ordinary mouse runs to her feet, then stands on its hind legs and says 「房子牆壁裡有金塊。」 It is an animal, not a person.",
             [("A small ordinary mouse runs across the floor to the adult woman's feet.", "", 4),
              ("The mouse stands upright on its hind legs and speaks. She crouches to listen. It says 「房子牆壁裡有金塊。」", "", 6)],
             tags="1girl, mouse, animal, crouching, indoor, solo",
             solo=True, scene="old apartment living room"),
        beat("續租", "apartment doorway, lease papers, afternoon, indoor",
             "She renews the lease with the landlord. He points at the signature line and says 「簽這裡。」",
             [("At the apartment door the landlord holds out a lease. She takes the pen.", "這房子，我續租。", 5),
              ("He points at the signature line. She signs. He says 「簽這裡。」", "", 5)],
             tags="1girl, 1boy, doorway, signing, indoor",
             partner=1, scene="apartment doorway"),
        beat("買鎚子", "hardware store, tool shelves, counter, daylight, indoor",
             "She runs into a hardware store. The owner stands behind the counter and sells her a hammer.",
             [("Hardware store. She runs in. The owner stands behind the counter.", "", 4),
              ("He sets a hammer on the counter. She takes it.", "鎚子，我買了。", 6)],
             tags="1girl, 1boy, hardware store, hammer, indoor",
             partner=2, scene="hardware store"),
        beat("砸牆發財", "old apartment living room, cracked plaster wall, hammer, afternoon, indoor",
             "She smashes the wall, gold nuggets pour out, and she laughs that she is rich. The story stops.",
             [("She strikes the cracked wall with the hammer until the plaster breaks.", "", 4),
              ("Gold nuggets pour out of the broken wall and pile on the floor.", "", 4),
              ("She looks at the gold and laughs.", "發財了！", 4)],
             tags="1girl, hammer, gold, wall, indoor, solo",
             solo=True, scene="old apartment living room"),
    ],
)
STORIES[sid] = body


def main():
    totals = {}
    for k, v in STORIES.items():
        t = sum(int(b["duration"]) for b in v["fragments"])
        totals[k] = (t, len(v["fragments"]))
        print(f"{k}: {t}s / {len(v['fragments'])} beats")
        if t > 180:
            raise SystemExit(f"{k} over 180s")
    OUT.write_text(json.dumps(STORIES, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT, totals)


if __name__ == "__main__":
    main()
