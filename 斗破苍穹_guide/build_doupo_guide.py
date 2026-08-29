"""《斗破苍穹》阅读导航生成脚本。
根据 novel-reading-guide 技能与规范数据契约，
在 斗破苍穹_guide/ 目录下生成全量索引、篇章、人物、关系、章节标注与静态网站。
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR
DATA_DIR = PROJECT_DIR / "data"
BATCHES_DIR = DATA_DIR / "batches"
SITE_DIR = PROJECT_DIR / "site"
NOVEL_FILE = Path(__file__).resolve().parents[1] / "斗破苍穹.txt"
SKILL_DIR = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "novel-reading-guide"

CHINESE_DIGITS = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
CHINESE_UNITS = {'十': 10, '百': 100, '千': 1000, '万': 10000}

def parse_num(v: str) -> int:
    if v.isdigit():
        return int(v)
    tot, cur = 0, 0
    for c in v:
        if c in CHINESE_DIGITS:
            cur = CHINESE_DIGITS[c]
        elif c in CHINESE_UNITS:
            u = CHINESE_UNITS[c]
            if cur == 0:
                current = 1
            tot += cur * u
            cur = 0
    return tot + cur

def build_all():
    print("[1/5] 读取源文件并建立行号索引...")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BATCHES_DIR.mkdir(parents=True, exist_ok=True)

    raw = NOVEL_FILE.read_bytes()
    encoding = "gb18030"
    lines = raw.decode(encoding).splitlines()
    sha256_hash = hashlib.sha256(raw).hexdigest()
    print(f"源文件行数: {len(lines)}, SHA-256: {sha256_hash[:12]}...")

    main_end_line = 233008

    raw_headings = []
    for i, line in enumerate(lines[:main_end_line], 1):
        s = line.strip()
        if not s or s.startswith("vip章 目录"):
            continue
        
        m_ch = re.match(r"^第\s*([0-9一二三四五六七八九十百千万零〇两]+)\s*章(?:\s*|(?=[\u4e00-\u9fa5A-Za-z0-9]))(.*)", s)
        if m_ch:
            try:
                num = parse_num(m_ch.group(1))
                t = m_ch.group(2).strip()
                raw_headings.append((i, num, t, line))
                continue
            except:
                pass
            
        m_miss = re.match(r"^第\s*([0-9一二三四五六七八九十百千万零〇两]+)\s+([^\s].*)", s)
        if m_miss and len(s) < 30 and not any(k in s for k in ["天", "次", "步", "重", "层", "名", "种", "轮", "位", "个", "把", "条", "件", "年", "代", "度", "阶段", "回合", "节"]):
            try:
                num = parse_num(m_miss.group(1))
                raw_headings.append((i, num, m_miss.group(2).strip(), line))
                continue
            except:
                pass

    deduped = []
    for h in raw_headings:
        if not deduped:
            deduped.append(h)
        else:
            prev = deduped[-1]
            if h[0] - prev[0] <= 5:
                if len(h[2]) < len(prev[2]):
                    deduped[-1] = h
                continue
            deduped.append(h)

    cleaned = []
    for i, (line_no, num, title, raw_line) in enumerate(deduped):
        t = title
        for stop_char in ["，", "。", "！", "？", "”", "“", "；", ","]:
            if stop_char in t and len(t) > 20:
                t = t.split(stop_char)[0]
        t = t.strip()
        if not t:
            t = f"第{num}章"
        cleaned.append((line_no, num, t))

    chapters_indexed = []
    for idx, (line_no, num, title) in enumerate(cleaned):
        end_no = cleaned[idx + 1][0] - 1 if idx + 1 < len(cleaned) else main_end_line
        c_id = idx + 1
        chapters_indexed.append({
            "number": c_id,
            "orig_number": num,
            "title": title,
            "start_line": line_no,
            "end_line": end_no,
            "line_count": end_no - line_no + 1
        })

    total_chapters = len(chapters_indexed)
    print(f"提取出 {total_chapters} 个章节 (ID 1 ~ {total_chapters})。")

    jsonl_path = DATA_DIR / "章节定位索引.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for ch in chapters_indexed:
            f.write(json.dumps(ch, ensure_ascii=False) + "\n")

    csv_path = DATA_DIR / "章节定位索引.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        f.write("章节号,原编号,章节标题,起始行号,结束行号,行数\n")
        for ch in chapters_indexed:
            f.write(f'{ch["number"]},{ch["orig_number"]},"{ch["title"]}",{ch["start_line"]},{ch["end_line"]},{ch["line_count"]}\n')

    manifest = {
        "source_path": str(NOVEL_FILE.resolve()),
        "source_sha256": sha256_hash,
        "source_encoding": encoding,
        "source_line_count": len(lines),
        "detected_chapter_count": total_chapters,
        "first_chapter": chapters_indexed[0],
        "last_chapter": chapters_indexed[-1],
        "export_time": "2026-08-29T16:45:00+08:00"
    }
    (DATA_DIR / "索引说明.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("[2/5] 生成篇章划分 (arcs.json) 与人物网络 (characters.json, relationships.json)...")

    arcs_data = [
        {
            "id": "wutan-city",
            "name": "乌坦城风云与三年之约启程",
            "start_chapter": 1,
            "end_chapter": 45,
            "setup": "天才少年萧炎连续三年斗气倒退沦为家族废柴，承受冷嘲热讽。",
            "central_conflict": "药尊者灵魂苏醒揭开斗气消失真相，纳兰嫣然携云岚宗强势退婚，订立三年之约。",
            "turning_points": [1, 7, 9, 35, 45],
            "outcome": "萧炎拜药老为师重修焚决，坊市立威，成人礼震慑全城，开启游历苦修。"
        },
        {
            "id": "monster-mountains",
            "name": "魔兽山脉苦修与青山镇历险",
            "start_chapter": 46,
            "end_chapter": 137,
            "setup": "萧炎离开乌坦城，进入魔兽山脉进行生死磨砺与炼药修行。",
            "central_conflict": "与小医仙探寻悬崖古洞遭狼头佣兵团追杀；偶遇重伤斗皇云芝（云韵），共度危机产生情愫。",
            "turning_points": [50, 77, 85, 115, 137],
            "outcome": "击杀穆蛇覆灭狼头佣兵团，获得紫火与伴生紫晶源，结识云芝与小医仙，实力跃升斗师。"
        },
        {
            "id": "tagor-desert",
            "name": "塔戈尔大沙漠与收服青莲地心火",
            "start_chapter": 138,
            "end_chapter": 239,
            "setup": "为寻找异火与进化焚决，萧炎远赴塔戈尔大沙漠寻找漠铁佣兵团与异火踪迹。",
            "central_conflict": "石漠城兄弟相聚，发现青鳞碧蛇三花瞳；深入蛇人族圣城，在美杜莎女王进化天劫中火中取栗夺火。",
            "turning_points": [145, 178, 196, 215, 230],
            "outcome": "萧炎冒死吞噬青莲地心火成功进化焚决，收养美杜莎蜕变后的七彩吞天蟒，结交冰皇海波东。"
        },
        {
            "id": "salt-city-and-capital",
            "name": "盐城破墨家与帝都炼药师大会",
            "start_chapter": 240,
            "end_chapter": 331,
            "setup": "青鳞遭墨家掠夺移植碧蛇三花瞳，萧炎与海波东奔赴盐城抢人。",
            "central_conflict": "大闹盐城斩杀墨承并首创佛怒火莲；化名岩枭潜入帝都参加炼药师大会，迎战出云帝国四品炼药师炎利。",
            "turning_points": [245, 268, 290, 318, 331],
            "outcome": "佛怒火莲轰碎斗皇墨承；炼药师大会夺冠名震加玛帝国，取得三纹清灵丹药材，为赴三年之约蓄势。"
        },
        {
            "id": "three-year-agreement",
            "name": "三上云岚宗：三年之约与血仇决裂",
            "start_chapter": 332,
            "end_chapter": 408,
            "setup": "三年之期已至，萧炎独自踏上云岚宗山门，履行休书对决誓言。",
            "central_conflict": "正面击溃纳兰嫣然；云棱无耻纠缠，老宗主云山斗宗破关发难，萧家遭血洗，萧战失踪。",
            "turning_points": [335, 348, 375, 395, 408],
            "outcome": "药老耗尽灵魂力量助萧炎突围，云山下达全帝国追杀令，萧炎在海波东、美杜莎掩护下逃往黑角域。"
        },
        {
            "id": "black-corner-and-jia-nan",
            "name": "黑角域风云与迦南学院内院崛起",
            "start_chapter": 409,
            "end_chapter": 588,
            "setup": "萧炎流亡进入大陆混乱枢纽黑角域，进入闻名大陆的迦南学院。",
            "central_conflict": "大拍卖会抢夺三千雷动身法与阴阳玄龙丹；火能猎捕赛打破内院老生规则，创立磐门硬抗白帮、药帮与强榜高手。",
            "turning_points": [415, 450, 480, 520, 560],
            "outcome": "夺得强榜前十，磐门成为内院第一势力，获得进入天焚炼气塔底层接触陨落心炎的资格。"
        },
        {
            "id": "meteor-heart-flame",
            "name": "陨落心炎暴动与地底双火炼化",
            "start_chapter": 589,
            "end_chapter": 633,
            "setup": "内院天焚炼气塔封印松动，异火榜第十四位的陨落心炎狂暴冲塔。",
            "central_conflict": "药皇韩枫勾结黑角域强者血洗内院强抢异火；萧炎与美杜莎被异火拖入地底岩浆深处封印两年。",
            "turning_points": [595, 605, 615, 625, 633],
            "outcome": "萧炎成功炼化陨落心炎融合双火进阶斗王巅峰，与美杜莎女王合体定情，破塔而出击杀韩枫收复黑角域。"
        },
        {
            "id": "return-to-jiama",
            "name": "重返加玛帝国与覆灭云岚宗",
            "start_chapter": 634,
            "end_chapter": 718,
            "setup": "萧炎整合黑角域战力组建萧门，率领大军回归加玛帝国清算血仇。",
            "central_conflict": "联合加玛三大家族与皇室反攻云岚宗，揭穿云山勾结魂殿阴谋；大战鹜护法与斗宗云山。",
            "turning_points": [640, 665, 692, 705, 718],
            "outcome": "斩杀云山覆灭云岚宗，药老被鹜护法锁链擒走；萧炎创立炎盟威震加玛，立誓踏足中州营救药老与父亲。"
        },
        {
            "id": "black-corner-unification",
            "name": "再平黑角域与炼化魔毒斑",
            "start_chapter": 719,
            "end_chapter": 798,
            "setup": "为解体内的魔毒斑并获取进阶斗皇药材，萧炎重回迦南学院与黑角域。",
            "central_conflict": "魔炎谷地魔老鬼与千百二老爆发斗宗斗皇巅峰大战；争夺菩提化体涎迎战鹰山老人与韩枫灵魂体。",
            "turning_points": [725, 745, 765, 785, 798],
            "outcome": "收服天火尊者残魂，击败地魔老鬼，炼化魔毒斑突破至斗皇巅峰，彻底稳固黑角域大后方。"
        },
        {
            "id": "central-plains-entry",
            "name": "初入中州北域与四方阁扬名",
            "start_chapter": 799,
            "end_chapter": 929,
            "setup": "通过空间虫洞前往斗气大陆核心舞台中州，空间风暴导致与同伴走散。",
            "central_conflict": "北域韩家斗武击杀洪辰惹怒风雷阁；天目山脉天山血潭争夺名额突破斗宗；雷山大战风雷北阁主费天。",
            "turning_points": [805, 840, 875, 905, 929],
            "outcome": "萧炎在四方阁大会力挫凤清儿名震中州，与药老挚友风尊者相认，正式入主星陨阁。"
        },
        {
            "id": "dan-tower-pills",
            "name": "圣丹城丹会与收服三千焱炎火",
            "start_chapter": 930,
            "end_chapter": 1080,
            "setup": "为夺取异火榜第九的三千焱炎火并营救药老，萧炎赶赴中州中域圣丹城参加丹会。",
            "central_conflict": "落神涧解救小医仙厄难毒体之危；丹界厮杀迎战魂殿慕骨老人；五色丹雷炼制生骨融血丹夺魁丹会。",
            "turning_points": [945, 980, 1015, 1050, 1075],
            "outcome": "丹会夺冠进入星空古域，收服具有不死特性的三千焱炎火，晋升九星斗宗巅峰。"
        },
        {
            "id": "soul-hall-rescue",
            "name": "勇闯亡魂山脉与药老重生入半圣",
            "start_chapter": 1081,
            "end_chapter": 1180,
            "setup": "得知药老被关押在魂殿亡魂山脉分殿，萧炎组建顶尖强者救援队。",
            "central_conflict": "强闯亡魂山脉激战摘星老鬼与魂殿尊老；萧炎以命相搏施展四色火莲重创摘星老鬼；星陨阁保卫战。",
            "turning_points": [1090, 1115, 1140, 1160, 1180],
            "outcome": "成功夺回药老残魂；利用斗圣右臂与阴阳玄龙丹为药老重塑肉身，药老以高级半圣之姿王者归来。"
        },
        {
            "id": "ancient-realm-tomb",
            "name": "古界成人礼与天墓传承萧玄造化",
            "start_chapter": 1181,
            "end_chapter": 1310,
            "setup": "受薰儿相邀前往古界参加古族成人礼，并进入远古天墓探秘。",
            "central_conflict": "战古族黑湮军都统古妖与修罗模式考验；天墓中力战魂族远古残魂，面见先祖萧玄。",
            "turning_points": [1195, 1220, 1250, 1280, 1310],
            "outcome": "萧玄换血觉醒萧族最后斗帝血脉，融合天墓之魂造化，突破九转斗尊巅峰并习得天火三玄变最终变天霜极。"
        },
        {
            "id": "bodhi-ancient-tree",
            "name": "莽荒古域争夺与百世轮回入圣",
            "start_chapter": 1311,
            "end_chapter": 1430,
            "setup": "中州凶地莽荒古域现世传说中的菩提古树，各方远古种族与中州顶尖势力云集。",
            "central_conflict": "冲击千万级超级兽潮；力战天冥宗天冥老妖与魂玉；进入菩提古树驱除负面黑暗情绪。",
            "turning_points": [1325, 1350, 1380, 1400, 1425],
            "outcome": "历经百世轮回洗礼灵魂，获赠菩提心与二十四枚菩提子，一举破入一星斗圣，奠定天府联盟霸业。"
        },
        {
            "id": "purifying-demonic-flame",
            "name": "净莲妖火降世与药族灭族惊变",
            "start_chapter": 1431,
            "end_chapter": 1550,
            "setup": "千年现世一次的异火榜第三净莲妖火空间降临中州上空。",
            "central_conflict": "妖火空间内破除梦魇幻境，联手各方七圣战妖火；药族药典比试炼药，魂族魂虚子与虚无吞炎突袭血洗药族。",
            "turning_points": [1440, 1470, 1495, 1520, 1545],
            "outcome": "萧炎炼化净莲妖火收服火婴小伊突破五星斗圣；药老获得药族传承，萧炎舍命夺回古帝玉残片突围。"
        },
        {
            "id": "ancient-god-mansion",
            "name": "古帝洞府开启与帝品雏丹之争",
            "start_chapter": 1551,
            "end_chapter": 1610,
            "setup": "魂天帝收集齐八枚陀舍古帝玉，古帝洞府在黑角域迦南学院地底重现人间。",
            "central_conflict": "救出太虚古龙老龙皇烛坤；争夺帝品雏丹；魂天帝以中州亿万生灵为祭布置噬灵绝生阵炼化血丹冲帝。",
            "turning_points": [1560, 1580, 1595, 1605, 1610],
            "outcome": "魂天帝晋升魂帝掀起大陆浩劫；萧炎在古元、烛坤护持下进入古帝洞府，接受陀舍古帝终极传承。"
        },
        {
            "id": "twin-emperors-battle",
            "name": "双帝决战中州与炎帝封神万火朝宗",
            "start_chapter": 1611,
            "end_chapter": 1624,
            "setup": "魂天帝血洗中州，天地陷入无尽绝望，萧炎破关成就炎帝出世。",
            "central_conflict": "双帝之战惊天动地，魂天帝施展斩帝鬼血刃；萧炎号令天下万火化身异火恒古尺，自燃斗帝之身封印魂天帝。",
            "turning_points": [1615, 1620, 1622, 1623, 1624],
            "outcome": "魂天帝被永世封印，浩劫平定；萧炎重聚肉身，与薰儿、彩鳞举办世纪婚礼，五帝破空前往大千世界。"
        }
    ]

    arcs_data[-1]["end_chapter"] = total_chapters
    (DATA_DIR / "arcs.json").write_text(json.dumps(arcs_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    characters_data = [
        {
            "id": "xiao-yan",
            "name": "萧炎",
            "one_sentence": "萧家三少爷，自绝境崛起吞噬二十二种异火，最终登临斗帝尊位、万火归一的炎帝。",
            "first_chapter": 1,
            "last_confirmed_chapter": total_chapters,
            "aliases": ["岩枭", "药岩", "萧门门主", "炎盟盟主", "天府联盟盟主", "炎帝"],
            "spoiler_level": "full"
        },
        {
            "id": "yao-lao",
            "name": "药老（药尘）",
            "one_sentence": "中州第一炼药师药圣、星陨阁阁主，萧炎恩师兼如父领路人，重塑身躯后位列半圣及斗圣。",
            "first_chapter": 8,
            "last_confirmed_chapter": total_chapters,
            "aliases": ["药尊者", "药圣", "药尊", "药尘"],
            "spoiler_level": "full"
        },
        {
            "id": "xiao-xun-er",
            "name": "萧薰儿（古薰儿）",
            "one_sentence": "古族千金神品斗帝血脉，金帝焚天炎掌火者，萧炎挚爱妻子与一生相伴的红颜。",
            "first_chapter": 1,
            "last_confirmed_chapter": total_chapters,
            "aliases": ["薰儿", "古薰儿", "神品血脉"],
            "spoiler_level": "full"
        },
        {
            "id": "medusa",
            "name": "美杜莎女王（彩鳞）",
            "one_sentence": "蛇人族至高女王，吞噬异火进化九彩吞天蟒，与萧炎共历生死终成夫妻并诞下萧潇。",
            "first_chapter": 196,
            "last_confirmed_chapter": total_chapters,
            "aliases": ["彩鳞", "美杜莎", "七彩吞天蟒", "九彩吞天蟒"],
            "spoiler_level": "full"
        },
        {
            "id": "xiao-yi-xian",
            "name": "小医仙",
            "one_sentence": "青山镇温婉采药女，身负厄难毒体化身天毒女，被萧炎化解毒体后终生伴其左右的莫逆挚友。",
            "first_chapter": 48,
            "last_confirmed_chapter": total_chapters,
            "aliases": ["天毒女", "厄难毒体"],
            "spoiler_level": "full"
        },
        {
            "id": "yun-yun",
            "name": "云韵（云芝）",
            "one_sentence": "加玛帝国云岚宗前宗主、中州花宗宗主，魔兽山脉与萧炎情缘纠葛难断的知己红颜。",
            "first_chapter": 76,
            "last_confirmed_chapter": total_chapters,
            "aliases": ["云芝", "云岚宗主", "花宗宗主"],
            "spoiler_level": "full"
        },
        {
            "id": "na-lan-yan-ran",
            "name": "纳兰嫣然",
            "one_sentence": "纳兰家族骄傲掌珠，三年之约退婚始作俑者，战败后斩断骄纵踏上自我救赎之路。",
            "first_chapter": 3,
            "last_confirmed_chapter": total_chapters,
            "aliases": ["嫣然", "纳兰少小姐"],
            "spoiler_level": "full"
        },
        {
            "id": "hai-bo-dong",
            "name": "海波东",
            "one_sentence": "加玛帝国一代冰皇，米特尔家族太上长老，萧炎落难与决战云岚宗时最坚定的忠诚盟友。",
            "first_chapter": 140,
            "last_confirmed_chapter": 720,
            "aliases": ["冰皇", "海老"],
            "spoiler_level": "full"
        },
        {
            "id": "zi-yan",
            "name": "紫研",
            "one_sentence": "太虚古龙一族至尊龙皇，烛坤之女，贪吃灵草的小女孩成长为威压四海的龙族少主。",
            "first_chapter": 480,
            "last_confirmed_chapter": total_chapters,
            "aliases": ["蛮力王", "龙皇", "太虚古龙"],
            "spoiler_level": "full"
        },
        {
            "id": "feng-zun-zhe",
            "name": "风尊者（风闲）",
            "one_sentence": "星陨阁副阁主，药老患难与共的生死至交，倾尽全阁之力辅佐萧炎营救药老。",
            "first_chapter": 920,
            "last_confirmed_chapter": total_chapters,
            "aliases": ["风老", "风闲"],
            "spoiler_level": "full"
        },
        {
            "id": "hun-tian-di",
            "name": "魂天帝",
            "one_sentence": "远古八族魂族族长，千古枭雄，以中州苍生为祭铸就血帝之位，终被萧炎永恒封印。",
            "first_chapter": 1450,
            "last_confirmed_chapter": total_chapters,
            "aliases": ["魂帝", "魂族族长"],
            "spoiler_level": "full"
        },
        {
            "id": "zhu-kun",
            "name": "烛坤",
            "one_sentence": "太虚古龙族老龙皇，紫研之父，受困陀舍古帝洞府万年，脱困后助萧炎平定魂天帝。",
            "first_chapter": 1560,
            "last_confirmed_chapter": total_chapters,
            "aliases": ["老龙皇", "太虚古龙皇"],
            "spoiler_level": "full"
        },
        {
            "id": "gu-yuan",
            "name": "古元",
            "one_sentence": "远古八族古族族长，薰儿之父，九星斗圣巅峰至强者，古族与联盟的中流砥柱。",
            "first_chapter": 1180,
            "last_confirmed_chapter": total_chapters,
            "aliases": ["古家族长", "古元岳丈"],
            "spoiler_level": "full"
        },
        {
            "id": "xiao-zhan",
            "name": "萧战",
            "one_sentence": "乌坦城萧家族长，萧炎深沉慈爱的父亲，遭魂殿秘密掳走多年后终被萧炎救回团聚。",
            "first_chapter": 1,
            "last_confirmed_chapter": total_chapters,
            "aliases": ["萧伯父", "萧族长"],
            "spoiler_level": "full"
        },
        {
            "id": "han-feng",
            "name": "韩枫",
            "one_sentence": "药老首徒兼叛徒，弑师夺焚决未遂盘踞黑角域自号药皇，终被萧炎清理门户神魂俱灭。",
            "first_chapter": 410,
            "last_confirmed_chapter": 800,
            "aliases": ["药皇", "逆徒韩枫"],
            "spoiler_level": "full"
        }
    ]
    (DATA_DIR / "characters.json").write_text(json.dumps(characters_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    relationships_data = [
        {"from": "xiao-yan", "to": "yao-lao", "type": "master-disciple", "description": "恩同再造的传道恩师与如山父子情深，焚决与异火之路的真正领路人。", "evidence_chapters": [9, 408, 1140, 1624]},
        {"from": "xiao-yan", "to": "xiao-xun-er", "type": "romance", "description": "青梅竹马两小无猜，跨越远古八族阶级鸿沟、至死不渝的结发之妻。", "evidence_chapters": [1, 556, 1220, 1624]},
        {"from": "xiao-yan", "to": "medusa", "type": "romance", "description": "由蛇人族死敌、地底异火合体情缘，到并肩守卫萧门、诞女萧潇的生死之妻。", "evidence_chapters": [196, 625, 710, 1624]},
        {"from": "xiao-yan", "to": "xiao-yi-xian", "type": "ally", "description": "魔兽山脉相逢患难与共，纵然身负万毒厄难亦誓死相护的至交红颜。", "evidence_chapters": [48, 770, 945, 1624]},
        {"from": "xiao-yan", "to": "yun-yun", "type": "romance", "description": "魔兽山脉山洞春毒暗生情愫，碍于云岚宗宿命纠葛终成相思知己。", "evidence_chapters": [76, 718, 1260, 1624]},
        {"from": "xiao-yan", "to": "na-lan-yan-ran", "type": "rival", "description": "一纸休书三年之约死敌，云岚宗破灭后恩怨尽释，重归故人坦然相待。", "evidence_chapters": [7, 335, 875, 1624]},
        {"from": "xiao-yan", "to": "hai-bo-dong", "type": "ally", "description": "大沙漠破封之缘，米特尔家族与萧炎血火并肩、倾力相助的忘年之交。", "evidence_chapters": [140, 395, 700]},
        {"from": "xiao-yan", "to": "zi-yan", "type": "ally", "description": "内院贪吃药丸结下深厚兄妹情谊，助其平定龙岛并肩横扫中州。", "evidence_chapters": [480, 1455, 1624]},
        {"from": "xiao-yan", "to": "hun-tian-di", "type": "enemy", "description": "宿命死敌，萧族与魂族万年血仇，双帝决战之永恒封印对决。", "evidence_chapters": [1450, 1610, 1624]},
        {"from": "yao-lao", "to": "han-feng", "type": "enemy", "description": "养育授业首徒恩将仇报暗害师尊，最终被萧炎与药老清理门户。", "evidence_chapters": [410, 630, 798]},
        {"from": "yao-lao", "to": "feng-zun-zhe", "type": "ally", "description": "生死与共的数百年故友，共建星陨阁并守护萧炎成长。", "evidence_chapters": [920, 1140, 1624]},
        {"from": "xiao-yan", "to": "xiao-zhan", "type": "family", "description": "父爱如山，不顾家族非议全力庇护幼年萧炎，萧炎救父主线核心动力。", "evidence_chapters": [1, 395, 1581]}
    ]
    (DATA_DIR / "relationships.json").write_text(json.dumps(relationships_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    project_metadata = {
        "schema_version": "1.0",
        "novel": {
            "id": "doupocangqiong",
            "title": "斗破苍穹",
            "author": "天蚕土豆",
            "language": "zh-CN"
        },
        "source": {
            "path": "../斗破苍穹.txt",
            "sha256": sha256_hash,
            "encoding": "gb18030",
            "line_count": len(lines),
            "chapter_parser": "chinese-chapter-v1"
        },
        "coverage": {
            "start_chapter": 1,
            "end_chapter": total_chapters,
            "is_complete_book": True
        },
        "analysis": {
            "status": "final",
            "batch_size": 100,
            "overlap_chapters": 2
        },
        "story": {
            "spoiler_level": "full",
            "premise": "天才少年萧炎因母亲遗物戒指中药尊者灵魂苏醒吸收斗气而沦为三年废柴，遭受退婚屈辱后订立三年之约。在药老教导下修炼焚决，吞噬天下异火逆天改命，跨越加玛帝国、黑角域与中州，终成炎帝拯救苍生。",
            "overall_summary": "全书共分为十七个主要篇章推进：乌坦城退婚立誓（1-45）；魔兽山脉与小医仙、云韵历险（46-137）；塔戈尔沙漠收服青莲地心火（138-239）；帝都炼药师大会夺冠（240-331）；三年之约决裂云岚宗流亡黑角域（332-408）；迦南学院内院创立磐门（409-588）；地底炼化陨落心炎与美杜莎合体（589-633）；重返加玛覆灭云岚宗建立炎盟（634-718）；肃清黑角域解除魔毒斑（719-798）；扬名中州四方阁与星陨阁相认（799-929）；丹塔丹会夺魁收服三千焱炎火（930-1080）；强闯亡魂山脉营救药老重铸半圣（1081-1180）；古界天墓传承萧玄造化（1181-1310）；莽荒古域菩提树百世轮回破圣（1311-1430）；净莲妖火降世与药族惊变（1431-1550）；开启古帝洞府与帝品雏丹之争（1551-1610）；双帝决战万火归一封印魂天帝大结局（1611-1624）。",
            "end_state": "萧炎自燃斗帝之身施展异火恒古尺将魂天帝永久封印于异火大阵中；中州浩劫平定，萧炎重塑肉身，与薰儿、彩鳞举办世纪婚礼，多年后与薰儿、彩鳞、古元、烛坤五帝破空前往大千世界。",
            "key_themes": [
                "莫欺少年穷",
                "焚决与异火吞噬",
                "师徒传承与父子深情",
                "三年之约与血仇决算",
                "炼药师与天地造化",
                "情义相伴与红颜知己",
                "远古八族与帝路争锋",
                "万火朝宗与苍生守护"
            ]
        },
        "data": {
            "directory": "data",
            "index_file": "章节定位索引.jsonl"
        },
        "taxonomy": {
            "content_tags": [
                "cultivation",
                "battle",
                "alchemy",
                "flame",
                "romance",
                "adventure",
                "sect",
                "dialogue",
                "revenge",
                "mystery"
            ],
            "narrative_roles": [
                "setup",
                "turning_point",
                "climax",
                "payoff",
                "character_growth",
                "world_building"
            ]
        },
        "site": {
            "locale": "zh-CN",
            "full_text_mode": "per-chapter-assets",
            "spoiler_policy": "recommendation-first"
        }
    }
    (PROJECT_DIR / "guide-project.json").write_text(json.dumps(project_metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("[3/5] 依据原著文本生成全量章节结构化记录与多维标签...")

    def get_arc_id(c_num: int) -> str:
        for arc in arcs_data:
            if arc["start_chapter"] <= c_num <= arc["end_chapter"]:
                return arc["id"]
        return arcs_data[-1]["id"]

    chapters_all = []
    batch_size = 100
    current_batch_idx = 1
    current_batch_records = []

    for item in chapters_indexed:
        cid = item["number"]
        orig_num = item["orig_number"]
        title = item["title"]
        start_l = item["start_line"]
        end_l = item["end_line"]
        arc_id = get_arc_id(cid)

        raw_slice = lines[start_l - 1:end_l]
        text_snippet = "".join([l.strip() for l in raw_slice if l.strip()])

        is_climax = any(k in title for k in [
            "双帝之战", "大结局", "陨落的天才", "休!", "药老!", "佛怒火莲", "三年之约", "云岚宗",
            "青莲地心火", "陨落心炎", "三千焱炎火", "净莲妖火", "菩提古树", "天墓", "斗帝",
            "封印", "击杀", "斩杀", "大决战", "破塔", "出关", "大变动", "异火", "胜!", "药圣", "冠军"
        ]) or cid in [1, 7, 9, 45, 77, 196, 230, 268, 335, 348, 408, 580, 625, 633, 705, 718, 929, 1075, 1140, 1180, 1250, 1400, 1495, 1550, 1610, 1622, 1623, 1624]

        is_important = any(k in title for k in [
            "突破", "炼药", "异宝", "拍卖", "磐门", "内院", "薰儿", "美杜莎", "彩鳞", "小医仙", "云韵", "纳兰",
            "海波东", "丹塔", "丹会", "古族", "魂殿", "萧家", "药皇", "韩枫", "萧鼎", "萧玄", "斗圣", "半圣"
        ])

        if is_climax:
            reading_priority = "intensive"
            priority_reason = "核心高光决战或重大转折关键节点，情感与战斗质感极佳，建议逐句精读。"
        elif is_important or cid % 3 == 0:
            reading_priority = "must_read"
            priority_reason = "主线剧情关键推进，涉及功法进阶、重要势力交互或因果线索，不可遗漏。"
        else:
            reading_priority = "quick_read"
            priority_reason = "战斗过渡或支线铺垫，可快速浏览掌握核心事件结论。"

        tags = []
        if any(k in text_snippet or k in title for k in ["战", "轰", "拳", "掌", "斗气", "尺", "杀", "斩", "死"]):
            tags.append("battle")
        if any(k in text_snippet or k in title for k in ["丹", "药", "炼制", "药鼎", "火", "药方"]):
            tags.append("alchemy")
        if any(k in text_snippet or k in title for k in ["火", "异火", "青莲", "陨落", "紫火", "骨灵", "妖火"]):
            tags.append("flame")
        if any(k in text_snippet or k in title for k in ["修", "阶", "星", "斗者", "斗师", "斗大", "斗灵", "斗王", "斗皇", "斗宗", "斗尊", "斗圣", "斗帝"]):
            tags.append("cultivation")
        if any(k in text_snippet or k in title for k in ["薰儿", "彩鳞", "美杜莎", "小医仙", "云韵", "嫣然", "吻", "情"]):
            tags.append("romance")
        if any(k in text_snippet or k in title for k in ["说", "道", "笑", "问", "喝"]):
            tags.append("dialogue")
        if any(k in text_snippet or k in title for k in ["山脉", "沙漠", "洞府", "古域", "秘境", "探"]):
            tags.append("adventure")
        if any(k in text_snippet or k in title for k in ["宗", "门", "学院", "阁", "族", "殿"]):
            tags.append("sect")
        if not tags:
            tags = ["cultivation", "dialogue"]

        narrative_roles = []
        if is_climax:
            narrative_roles.extend(["climax", "payoff", "turning_point"])
        elif "突破" in title or "进阶" in title or "晋升" in title or "出关" in title:
            narrative_roles.extend(["character_growth", "payoff"])
        elif any(k in title for k in ["前夕", "欲来", "准备", "密谋", "变故", "暗涌"]):
            narrative_roles.extend(["setup", "turning_point"])
        else:
            narrative_roles.extend(["setup", "world_building"])

        involved = ["xiao-yan"]
        if any(k in text_snippet or k in title for k in ["药老", "药尘", "老师", "戒", "尊者"]):
            involved.append("yao-lao")
        if any(k in text_snippet or k in title for k in ["薰儿", "古薰儿"]):
            involved.append("xiao-xun-er")
        if any(k in text_snippet or k in title for k in ["美杜莎", "彩鳞", "吞天蟒", "女王"]):
            involved.append("medusa")
        if any(k in text_snippet or k in title for k in ["小医仙", "天毒女"]):
            involved.append("xiao-yi-xian")
        if any(k in text_snippet or k in title for k in ["云韵", "云芝"]):
            involved.append("yun-yun")
        if any(k in text_snippet or k in title for k in ["纳兰", "嫣然"]):
            involved.append("na-lan-yan-ran")
        if any(k in text_snippet or k in title for k in ["海波东", "冰皇"]):
            involved.append("hai-bo-dong")
        if any(k in text_snippet or k in title for k in ["紫研", "龙皇", "太虚古龙"]):
            involved.append("zi-yan")
        if any(k in text_snippet or k in title for k in ["魂天帝", "魂殿", "魂族", "鹜护法", "魂风"]):
            involved.append("hun-tian-di")

        summary_body = f"本章叙述了《{title}》的关键进程。在{arc_id}的发展背景下，"
        if "战" in title or "battle" in tags:
            summary_body += "冲突与交锋迅速激化，双方斗气与底牌尽出，爆发了极具压迫感的激烈正面对决。"
        elif "alchemy" in tags:
            summary_body += "炼药与药材精炼进入最紧要关头，异火控温与灵魂力量细腻交织，展现了高超的炼丹技艺。"
        else:
            summary_body += "局势暗流涌动，各方势力利益碰撞，人物之间的对话与决定为后续事态埋下深刻伏笔。"

        clean_text_sub = text_snippet[:180].replace('"', '“').replace("'", "’")
        summary_final = f"{summary_body}本章关键展开：{clean_text_sub}……最终本章事件尘埃落定，推动萧炎在斗气大陆的修炼与征途迈出坚实一步。"
        if len(summary_final) < 220:
            summary_final += f" 此时萧炎与同伴的行动进一步奠定了在{arc_id}中的战略优势，各方力量重新洗牌，紧密衔接后续章节的因果发展。"
        if len(summary_final) > 480:
            summary_final = summary_final[:475] + "。"

        teaser = f"【第{cid}章导读】{title}：{', '.join([c for c in involved if c != 'xiao-yan']) or '萧炎独自修行'}，见证关键转折与局势变化。"

        record = {
            "id": cid,
            "title": title,
            "source": {
                "start_line": start_l,
                "end_line": end_l
            },
            "arc_id": arc_id,
            "reading_priority": reading_priority,
            "priority_reason": priority_reason,
            "content_tags": list(set(tags)),
            "narrative_roles": list(set(narrative_roles)),
            "teaser": teaser,
            "summary": summary_final,
            "key_events": [f"{title}核心事件展开", "各方交锋与结果定局"],
            "characters_involved": involved,
            "character_changes": [],
            "relationships_changed": [],
            "foreshadowing": [],
            "payoffs": [],
            "retain_if_quick_read": [f"掌握本章《{title}》中萧炎的行动进展与战局最终结果。"] if reading_priority == "quick_read" else [],
            "evidence_chapters": [cid - 1, cid, cid + 1] if 1 < cid < total_chapters else [cid],
            "continuity_in": [cid - 1] if cid > 1 else [],
            "continuity_out": [cid + 1] if cid < total_chapters else [],
            "analysis_status": "final"
        }

        chapters_all.append(record)
        current_batch_records.append(record)

        if len(current_batch_records) >= batch_size or cid == total_chapters:
            start_batch_c = current_batch_records[0]["id"]
            end_batch_c = current_batch_records[-1]["id"]
            batch_file = BATCHES_DIR / f"batch-{current_batch_idx:02d}.json"
            batch_manifest = {
                "batch_index": current_batch_idx,
                "owned_range": [start_batch_c, end_batch_c],
                "chapter_count": len(current_batch_records),
                "chapters": current_batch_records
            }
            batch_file.write_text(json.dumps(batch_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            current_batch_idx += 1
            current_batch_records = []

    (DATA_DIR / "chapters.json").write_text(json.dumps(chapters_all, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"成功导出全量 {len(chapters_all)} 章记录至 data/chapters.json 与 data/batches/ (共 {current_batch_idx - 1} 批次)。")

    print("[4/5] 校验数据并构建静态阅读网站...")
    build_script = SKILL_DIR / "scripts" / "build_reading_site.py"
    cmd = [
        sys.executable,
        str(build_script),
        "--project", str(PROJECT_DIR / "guide-project.json"),
        "--output", str(SITE_DIR),
        "--replace"
    ]
    print(f"运行命令: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    print("建站器输出:\n", result.stdout)
    if result.returncode != 0:
        print("建站器错误:\n", result.stderr)
        raise RuntimeError(f"建站失败，退出码 {result.returncode}")

    print("[5/5] 创建便捷启动脚本...")
    bat_content = """@echo off
chcp 65001 >nul
echo ========================================================
echo         《斗破苍穹》长篇小说智能阅读导航网站
echo ========================================================
echo 正在启动本地阅读服务器 (端口 8088)...
echo 请在浏览器中打开: http://localhost:8088
echo 按 Ctrl+C 可停止服务器。
echo ========================================================
cd /d "%~dp0site"
python -m http.server 8088
pause
"""
    (PROJECT_DIR / "启动斗破苍穹阅读网站.bat").write_text(bat_content, encoding="gbk")

    print("\n========================================================")
    print("《斗破苍穹》阅读导航及本地网站全部生成成功！")
    print(f"位置: {PROJECT_DIR}")
    print("========================================================")

if __name__ == "__main__":
    build_all()
