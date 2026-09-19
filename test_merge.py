
lines = [
    ("فرشید", "خبر اول جزئیات"),
    ("فرشید", "ادامه خبر اول"),
    ("پریسا", "واکنش"),
    ("فرشید", "جمعبندی"),
    ("پریسا", "خبر دوم"),
    ("پریسا", "ادامه خبر دوم"),
]
turns = []
for speaker, text in lines:
    if turns and turns[-1][0] == speaker:
        turns[-1] = (speaker, turns[-1][1] + " " + text)
    else:
        turns.append((speaker, text))
assert len(turns) == 4, turns
assert turns[0][1] == "خبر اول جزئیات ادامه خبر اول"
assert turns[2][1] == "جمعبندی"  # speaker switch, no merge
print("MERGE TEST PASSED:", len(turns), "turns from 6 lines")
