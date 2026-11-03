import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Math;

//! Text that always fits a round screen: wrap to the chord width at that height, truncate with "..." if needed.
(:glance)
module Txt {

    //! Usable width of a round display at height y (chord), minus a margin each side.
    function chord(dc as Dc, y as Numeric, margin as Numeric) as Number {
        var w = dc.getWidth();
        var r = w / 2.0;
        var dy = (y - dc.getHeight() / 2.0).abs();
        if (dy >= r) {
            return 0;
        }
        var c = 2 * Math.sqrt(r * r - dy * dy) - 2 * margin;
        return (c < w * 0.3 ? w * 0.3 : c).toNumber();
    }

    //! Shorten to fit maxW, adding "..." when cut.
    function fit(dc as Dc, text as String, font as Graphics.FontType, maxW as Numeric) as String {
        if (dc.getTextWidthInPixels(text, font) <= maxW) {
            return text;
        }
        var t = text;
        while (t.length() > 1 && dc.getTextWidthInPixels(t + "...", font) > maxW) {
            t = t.substring(0, t.length() - 1);
        }
        return t + "...";
    }

    //! Word-wrap into at most maxLines lines; the last line is truncated if there's more.
    function wrap(dc as Dc, text as String, font as Graphics.FontType, maxW as Numeric, maxLines as Number) as String {
        var words = [] as Array<String>;
        var cur = "";
        var chars = text.toCharArray();
        for (var i = 0; i < chars.size(); i++) {
            if (chars[i] == ' ' || chars[i] == '\n') {
                if (cur.length() > 0) {
                    words.add(cur);
                }
                if (chars[i] == '\n') {
                    words.add("\n");
                }
                cur = "";
            } else {
                cur += chars[i].toString();
            }
        }
        if (cur.length() > 0) {
            words.add(cur);
        }
        var lines = [] as Array<String>;
        var line = "";
        for (var j = 0; j < words.size(); j++) {
            if (words[j].equals("\n")) {
                lines.add(line);
                line = "";
                continue;
            }
            var trial = line.length() == 0 ? words[j] : line + " " + words[j];
            if (dc.getTextWidthInPixels(trial, font) <= maxW || line.length() == 0) {
                line = trial;
            } else {
                lines.add(line);
                line = words[j];
            }
        }
        if (line.length() > 0) {
            lines.add(line);
        }
        var out = "";
        var n = lines.size() < maxLines ? lines.size() : maxLines;
        for (var k = 0; k < n; k++) {
            var l = lines[k];
            if (k == n - 1 && lines.size() > maxLines) {
                l = fit(dc, l + " " + lines[k + 1], font, maxW);
            } else {
                l = fit(dc, l, font, maxW);
            }
            out += (k > 0 ? "\n" : "") + l;
        }
        return out;
    }

    //! Draw centred text wrapped to the chord at y; returns the height used.
    function block(dc as Dc, x as Numeric, y as Numeric, text as String, font as Graphics.FontType, maxLines as Number) as Number {
        var fh = dc.getFontHeight(font);
        var width = chord(dc, y + fh * maxLines / 2, dc.getWidth() * 0.06);
        var s = wrap(dc, text, font, width, maxLines);
        dc.drawText(x, y, font, s, Graphics.TEXT_JUSTIFY_CENTER);
        var lines = 1;
        var cs = s.toCharArray();
        for (var i = 0; i < cs.size(); i++) {
            if (cs[i] == '\n') {
                lines += 1;
            }
        }
        return fh * lines;
    }
}
