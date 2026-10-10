"""False languages, to find the layouts that only break in a language that is longer than the one the widget was
written in. The studio shows a widget in one of these beside the real languages: any text that no longer fits is cut
(and reported), any that runs into another piece or out of the widget is reported with where.

    expand("Water today")        ->  "[Ŵàţéř ţǿďàý~~~~]"      letters accented, 40 % longer, brackets so a cut end shows
    expand("5 of 8 glasses")     ->  "[5 ǿƒ 8 ĝĺàšșéș~~~~~~]"
    expand("8")                  ->  "8"                       numbers and symbols alone are left as they are
"""
FROM = "AEIOUYaeiouyCcNnSsZzDdTtLlGgKkRrBbPpHhMmFfJjQqVvWwXx"
TO = "ÀÉÎÕÜÝàéîõüýÇçÑñŠšŽžĐđŢţĹĺĜĝĶķŔŕƁƀƤƥĤĥḾḿƑƒĴĵǪǫṼṽŴŵẊẋ"
_ACCENTS = str.maketrans(FROM, TO)


def _wide(c):
    return ord(c) >= 0x2E80                      # Chinese, Japanese, Korean: a character takes two letters' room


def expand(s, factor=0.4):
    """`s` made `factor` longer, in other-looking letters, between brackets."""
    if not any(c.isalpha() for c in s):
        return s
    pad = max(2, round(len(s) * factor))
    fill = "\uff5e" if any(_wide(c) for c in s) else "~"
    return "[" + s.translate(_ACCENTS) + fill * pad + "]"


def longer(factor):
    return lambda s: expand(s, factor)


MODES = {"pseudo": longer(0.4), "pseudo-zh": longer(0.4)}
