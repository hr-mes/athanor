//! Text from other processes made safe to show (doc_shell.md SH12, doc_bar.md BR4): control
//! characters and bidirectional formatting characters removed, then truncated to a number
//! of characters. Markup is never interpreted: the bar sets these strings as plain text, so
//! a tag shows as written.
// ponytail: the filter of athanor_trust_state::display (PR #64, not below this branch yet).
// Once it is, both call one function.

pub const NAME_CHARS: usize = 64;
pub const SUMMARY_CHARS: usize = 256;
pub const BODY_CHARS: usize = 2048;

/// One line: every control character goes, newlines too.
#[must_use]
pub fn line(text: &str, max_chars: usize) -> String {
    text.chars()
        .filter(|&c| !is_hidden(c))
        .take(max_chars)
        .collect()
}

/// Several lines: `\n` stays, `\r` and every other control character go.
#[must_use]
pub fn lines(text: &str, max_chars: usize) -> String {
    text.chars()
        .filter(|&c| c == '\n' || !is_hidden(c))
        .take(max_chars)
        .collect()
}

/// A control character (C0 and C1) or a bidirectional formatting character.
#[must_use]
pub fn is_hidden(c: char) -> bool {
    c.is_control()
        || matches!(c, '\u{061C}' | '\u{200E}' | '\u{200F}' | '\u{202A}'..='\u{202E}' | '\u{2066}'..='\u{2069}')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_line_loses_controls_bidi_and_newlines() {
        assert_eq!(line("a\u{202E}b\nc\td\u{0007}e\u{0085}", 64), "abcde");
    }

    #[test]
    fn lines_keep_newlines_and_drop_carriage_returns() {
        assert_eq!(lines("one\r\ntwo\u{2066}\u{0000}", 64), "one\ntwo");
    }

    #[test]
    fn markup_is_kept_as_written() {
        assert_eq!(lines("<b>bold</b> &amp;", 64), "<b>bold</b> &amp;");
    }

    #[test]
    fn truncation_counts_characters_not_bytes() {
        let cut = line(&"é".repeat(300), SUMMARY_CHARS);
        assert_eq!(cut.chars().count(), SUMMARY_CHARS);
    }
}
