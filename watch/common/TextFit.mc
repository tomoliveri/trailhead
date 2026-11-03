import Toybox.Graphics;
import Toybox.Lang;

module TextFit {
    // Draw each wrapped line explicitly; drawText/fitTextToArea alone can ellipsize instead.
    function draw(dc as Graphics.Dc, text as String, y as Numeric, width as Numeric, height as Numeric, font as Graphics.FontType) as Void {
        var lineHeight = dc.getFontHeight(font);
        var rows = (height / lineHeight).toNumber();
        var remaining = text;
        for (var row = 0; row < rows && remaining.length() > 0; row += 1) {
            var cut = remaining.length();
            for (var i = 1; i <= remaining.length(); i += 1) {
                if (remaining.substring(i - 1, i).equals("\n") || dc.getTextWidthInPixels(remaining.substring(0, i), font) > width) {
                    cut = i - 1;
                    break;
                }
            }
            if (cut < remaining.length() && !remaining.substring(cut, cut + 1).equals("\n")) {
                for (var j = cut; j > 0; j -= 1) {
                    if (remaining.substring(j - 1, j).equals(" ")) {
                        cut = j - 1;
                        break;
                    }
                }
            }
            if (cut == 0) { cut = 1; }
            var line = remaining.substring(0, cut);
            if (row == rows - 1 && cut < remaining.length()) {
                var fitted = Graphics.fitTextToArea(remaining, font, width, lineHeight, true);
                line = fitted != null ? fitted : line;
            }
            dc.drawText(dc.getWidth() / 2, y + row * lineHeight, font, line, Graphics.TEXT_JUSTIFY_CENTER);
            remaining = remaining.substring(cut, remaining.length());
            while (remaining.length() > 0 && (remaining.substring(0, 1).equals(" ") || remaining.substring(0, 1).equals("\n"))) {
                remaining = remaining.substring(1, remaining.length());
            }
        }
    }
}
