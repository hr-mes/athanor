//! Translations for Athanor's own programs.
//!
//! The format is gettext's: translators work on `.po` files with the tools they know,
//! and packages ship `.mo` catalogs under `/usr/share/locale`. The *reader* is ours, in
//! safe Rust with no dependency, for three reasons (doc_shell.md, SH13; decision of
//! 2026-09-19):
//!
//! - the greeter handles the password: no C FFI and no process-global
//!   `setlocale`/`textdomain` state in that process;
//! - glibc's gettext translates only when the system locale is installed, so it is
//!   silently English inside a sandbox or a test container that lacks the locale;
//! - it is toolkit-agnostic logic (SH4), usable by a surface and by a notifier alike.
//!
//! GTK's own strings keep going through the system's gettext, untouched.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// Where packages install catalogs.
pub const LOCALE_DIR: &str = "/usr/share/locale";
/// A catalog file to load instead of looking one up. For the test rig, where German and
/// the right-to-left pseudo-language are catalogs of the test, not of the product.
pub const OVERRIDE_VARIABLE: &str = "ATHANOR_I18N_CATALOG";

const SYSTEM_LOCALE_FILE: &str = "/etc/locale.conf";
const MAGIC: u32 = 0x9504_12de;
const CONTEXT_SEPARATOR: char = '\u{4}';
/// Languages written right to left. The direction comes from the language of the
/// catalog in use, never from a process-wide locale.
const RTL_LANGUAGES: [&str; 4] = ["ar", "he", "fa", "ur"];

#[derive(Debug, PartialEq, Eq)]
pub enum Error {
    /// Not a `.mo` file, or one cut short.
    Malformed(&'static str),
    /// A revision whose major number is not 0.
    UnsupportedRevision(u32),
    /// Only UTF-8 catalogs are read; `msgfmt` is told to write nothing else.
    NotUtf8,
    /// A `Plural-Forms` rule that is not in [`PluralRule`]'s table.
    UnknownPluralRule(String),
}

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Malformed(what) => write!(f, "malformed catalog: {what}"),
            Self::UnsupportedRevision(revision) => {
                write!(f, "unsupported catalog revision {revision:#x}")
            }
            Self::NotUtf8 => write!(f, "the catalog is not UTF-8"),
            Self::UnknownPluralRule(rule) => write!(f, "unknown plural rule: {rule}"),
        }
    }
}

impl std::error::Error for Error {}

/// The plural rules of the languages Athanor ships or tests, by their canonical
/// `Plural-Forms` expression. A table, not an expression evaluator: a catalog is data
/// read in the process that handles the password, and an evaluator is a parser and an
/// interpreter to get wrong there. A new language adds one line and one test.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PluralRule {
    /// `nplurals=1; plural=0` (Japanese, Chinese, ...).
    One,
    /// `nplurals=2; plural=(n != 1)` (English, Italian, German, Spanish, ...).
    NotOne,
    /// `nplurals=2; plural=(n > 1)` (French, Brazilian Portuguese).
    MoreThanOne,
    /// Arabic's six forms.
    Arabic,
}

impl PluralRule {
    fn parse(header: &str) -> Result<Self, Error> {
        let compact: String = header.chars().filter(|c| !c.is_whitespace()).collect();
        let compact = compact.trim_end_matches(';');
        Ok(match compact {
            "nplurals=1;plural=0" => Self::One,
            "nplurals=2;plural=(n!=1)" | "nplurals=2;plural=n!=1" => Self::NotOne,
            "nplurals=2;plural=(n>1)" | "nplurals=2;plural=n>1" => Self::MoreThanOne,
            "nplurals=6;plural=(n==0?0:n==1?1:n==2?2:n%100>=3&&n%100<=10?3:n%100>=11?4:5)"
            | "nplurals=6;plural=n==0?0:n==1?1:n==2?2:n%100>=3&&n%100<=10?3:n%100>=11?4:5" => {
                Self::Arabic
            }
            other => return Err(Error::UnknownPluralRule(other.to_string())),
        })
    }

    /// The index of the form for `n`.
    pub fn index(self, n: u64) -> usize {
        match self {
            Self::One => 0,
            Self::NotOne => usize::from(n != 1),
            Self::MoreThanOne => usize::from(n > 1),
            Self::Arabic => match (n, n % 100) {
                (0, _) => 0,
                (1, _) => 1,
                (2, _) => 2,
                (_, 3..=10) => 3,
                (_, 11..) => 4,
                _ => 5,
            },
        }
    }
}

/// One language's translations. An empty catalog returns every message id unchanged,
/// which is English.
#[derive(Debug)]
pub struct Catalog {
    /// Key: `msgid`, or `msgctxt` + EOT + `msgid`. Value: the plural forms, one for a
    /// message without a plural.
    messages: HashMap<String, Vec<String>>,
    plural: PluralRule,
    language: Option<String>,
}

impl Default for Catalog {
    fn default() -> Self {
        Self::empty()
    }
}

impl Catalog {
    pub fn empty() -> Self {
        Self {
            messages: HashMap::new(),
            plural: PluralRule::NotOne,
            language: None,
        }
    }

    /// Parses a `.mo` file of either byte order. Every offset is bounds-checked: a
    /// truncated or hostile file is an error, never a panic.
    pub fn parse(bytes: &[u8]) -> Result<Self, Error> {
        let word_at = |offset: usize, big_endian: bool| -> Result<u32, Error> {
            let raw: [u8; 4] = bytes
                .get(
                    offset
                        ..offset
                            .checked_add(4)
                            .ok_or(Error::Malformed("offset overflow"))?,
                )
                .and_then(|slice| slice.try_into().ok())
                .ok_or(Error::Malformed("truncated"))?;
            Ok(if big_endian {
                u32::from_be_bytes(raw)
            } else {
                u32::from_le_bytes(raw)
            })
        };
        let big_endian = match (word_at(0, false)?, word_at(0, true)?) {
            (MAGIC, _) => false,
            (_, MAGIC) => true,
            _ => return Err(Error::Malformed("not a .mo file")),
        };
        let word = |offset: usize| word_at(offset, big_endian).map(|value| value as usize);

        let revision = word_at(4, big_endian)?;
        if revision >> 16 != 0 {
            return Err(Error::UnsupportedRevision(revision));
        }
        let (count, originals, translations) = (word(8)?, word(12)?, word(16)?);

        let text = |table: usize, index: usize| -> Result<&str, Error> {
            let entry = index
                .checked_mul(8)
                .and_then(|offset| offset.checked_add(table))
                .ok_or(Error::Malformed("table overflow"))?;
            let (length, start) = (word(entry)?, word(entry + 4)?);
            let end = start
                .checked_add(length)
                .ok_or(Error::Malformed("string overflow"))?;
            let raw = bytes
                .get(start..end)
                .ok_or(Error::Malformed("string out of bounds"))?;
            std::str::from_utf8(raw).map_err(|_| Error::NotUtf8)
        };

        let mut catalog = Self::empty();
        for index in 0..count {
            let original = text(originals, index)?;
            let translation = text(translations, index)?;
            if original.is_empty() {
                catalog.read_header(translation)?;
                continue;
            }
            // A plural entry stores "msgid NUL msgid_plural"; the key is the singular.
            let key = original.split('\0').next().unwrap_or(original);
            catalog.messages.insert(
                key.to_string(),
                translation.split('\0').map(str::to_string).collect(),
            );
        }
        Ok(catalog)
    }

    fn read_header(&mut self, header: &str) -> Result<(), Error> {
        for line in header.lines() {
            let Some((name, value)) = line.split_once(':') else {
                continue;
            };
            let value = value.trim();
            match name.trim().to_ascii_lowercase().as_str() {
                "content-type" => {
                    let charset = value.rsplit("charset=").next().unwrap_or("");
                    if !charset.eq_ignore_ascii_case("utf-8") {
                        return Err(Error::NotUtf8);
                    }
                }
                "plural-forms" => self.plural = PluralRule::parse(value)?,
                "language" if !value.is_empty() => self.language = Some(value.to_string()),
                _ => {}
            }
        }
        Ok(())
    }

    /// The catalog of `domain` for the first language of `languages` that has one under
    /// `locale_dir`. A catalog that exists and cannot be read is an error, not a reason
    /// to fall through silently to the next language.
    pub fn find(
        locale_dir: &Path,
        domain: &str,
        languages: &[String],
    ) -> Result<Self, (PathBuf, Error)> {
        for language in languages {
            let path = locale_dir
                .join(language)
                .join("LC_MESSAGES")
                .join(format!("{domain}.mo"));
            if let Ok(bytes) = std::fs::read(&path) {
                let mut catalog = Self::parse(&bytes).map_err(|error| (path, error))?;
                catalog.language.get_or_insert_with(|| language.clone());
                return Ok(catalog);
            }
        }
        Ok(Self::empty())
    }

    /// What a program calls at start: the override file when [`OVERRIDE_VARIABLE`] names
    /// one, otherwise the catalog for the language of the environment, of
    /// `/etc/locale.conf`, or none. The error says which file was unreadable; the caller
    /// logs it and carries on in English with [`Catalog::empty`].
    pub fn load(domain: &str) -> Result<Self, (PathBuf, Error)> {
        if let Some(path) = std::env::var_os(OVERRIDE_VARIABLE).filter(|value| !value.is_empty()) {
            let path = PathBuf::from(path);
            let bytes = std::fs::read(&path)
                .map_err(|_| (path.clone(), Error::Malformed("unreadable override file")))?;
            return Self::parse(&bytes).map_err(|error| (path, error));
        }
        let system = std::fs::read_to_string(SYSTEM_LOCALE_FILE).ok();
        let languages = languages(|name| std::env::var(name).ok(), system.as_deref());
        Self::find(Path::new(LOCALE_DIR), domain, &languages)
    }

    pub fn tr<'a>(&'a self, msgid: &'a str) -> &'a str {
        self.form(msgid, 0).unwrap_or(msgid)
    }

    pub fn tr_n<'a>(&'a self, msgid: &'a str, msgid_plural: &'a str, n: u64) -> &'a str {
        match self.form(msgid, self.plural.index(n)) {
            Some(translated) => translated,
            None if n == 1 => msgid,
            None => msgid_plural,
        }
    }

    /// A message with a context (`msgctxt`), for a word that translates differently in
    /// two places.
    pub fn tr_c<'a>(&'a self, context: &str, msgid: &'a str) -> &'a str {
        let key = format!("{context}{CONTEXT_SEPARATOR}{msgid}");
        // The borrow of `key` ends here; the result borrows from `self` or `msgid`.
        match self.messages.get(&key).and_then(|forms| forms.first()) {
            Some(translated) if !translated.is_empty() => translated,
            _ => msgid,
        }
    }

    fn form(&self, msgid: &str, index: usize) -> Option<&str> {
        let forms = self.messages.get(msgid)?;
        forms
            .get(index)
            .map(String::as_str)
            .filter(|text| !text.is_empty())
    }

    /// The language of the catalog in use; `None` for the untranslated English.
    pub fn language(&self) -> Option<&str> {
        self.language.as_deref()
    }

    /// Whether the language in use is written right to left.
    pub fn is_rtl(&self) -> bool {
        self.language()
            .map(primary_language)
            .is_some_and(|language| RTL_LANGUAGES.contains(&language))
    }
}

fn primary_language(locale: &str) -> &str {
    locale.split(['_', '.', '@']).next().unwrap_or(locale)
}

/// The catalog directories to try, most specific first: `it_IT.UTF-8@euro` gives
/// `["it_IT", "it"]`. The locale is the first non-empty of `LC_ALL`, `LC_MESSAGES`,
/// `LANG` in the environment, else `LANG` of `/etc/locale.conf`. `C` and `POSIX` mean
/// untranslated.
pub fn languages(
    env: impl Fn(&str) -> Option<String>,
    system_locale_conf: Option<&str>,
) -> Vec<String> {
    let from_env = ["LC_ALL", "LC_MESSAGES", "LANG"]
        .into_iter()
        .find_map(|name| env(name).filter(|value| !value.is_empty()));
    let from_system = || {
        system_locale_conf?.lines().find_map(|line| {
            let value = line.trim().strip_prefix("LANG=")?;
            Some(value.trim_matches('"').to_string())
        })
    };
    let Some(locale) = from_env.or_else(from_system) else {
        return Vec::new();
    };
    let base = locale.split(['.', '@']).next().unwrap_or("");
    if base.is_empty() || base == "C" || base == "POSIX" {
        return Vec::new();
    }
    let mut found = vec![base.to_string()];
    let primary = primary_language(base);
    if primary != base {
        found.push(primary.to_string());
    }
    found
}
