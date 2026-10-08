"""The brain test cases: frame (eval/brain/frames, from the lab run of 2026-10-07), the step the wearer is on, what they say, and the
truth: the step after the answer (same = stay, +1 = move on) and what a right answer must say."""
CASES = [
    # id  frame              step  words                                   step after  a right answer
    ("A", "012-s1-correct",     1, "Okay, I put the red one on. Is it right?", 2, "right; give step 2"),
    ("B", "030-s2-wrong",       2, "So did I place it right?",                 2, "not right: purple lies left-right, must run front to back"),
    ("C", "042-s2-correct",     2, "Okay, how about now?",                     3, "right; give step 3"),
    ("D", "048-s3-not_placed",  3, "Is this one done?",                        3, "no lime 1x2 on the plate yet"),
    ("E", "075-s3-wrong",       3, "Okay, is that right?",                     3, "not right: lime must stick out one stud above the purple"),
    ("F", "112-s3-correct",     3, "Okay, how about now?",                     4, "right; give step 4"),
    ("G", "126-s4-wrong",       4, "Okay, done.",                              4, "not right: brick is tan/beige, needs white"),
    ("H", "140-s4-correct",     4, "I swapped it. Is it right now?",           5, "right; give step 5"),
    ("I", "180-s8-not_placed",  8, "Is it okay?",                              8, "white 1x4 at the right end not placed yet"),
    ("J", "218-s10-wrong",     10, "Like this?",                               10, "not right: rear disc too far right, must sit under blue/lime"),
    # K: the right wheel was built with four empty columns to the left wheel, the plan says three (the old judge
    # passed it; the wearer confirmed by eye on 2026-10-08): a right answer keeps step 10 and says so
    ("K", "231-s10-correct",   10, "Okay, how about now?",                     10, "not right: four empty columns between the wheels, should be three"),
    ("L", "270-s13-correct",   13, "Done, is that the last one?",              14, "right; build finished"),
    # general questions, step must not change
    ("M", "012-s1-correct",     2, "What am I holding in my right hand?",     2, "a purple brick (2x4)"),
    ("N", "270-s13-correct",   14, "How many red pieces are on the plate?",   14, "three: the slope and two discs"),
    ("O", "231-s10-correct",   11, "Are the two wheels the same size?",       11, "yes"),
]
