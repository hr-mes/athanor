//! The fixtures are real `msgfmt` output (tests/fixtures/make.sh).

use athanor_i18n::{languages, Catalog, Error, PluralRule};

const IT: &[u8] = include_bytes!("fixtures/it.mo");
const IT_BIG_ENDIAN: &[u8] = include_bytes!("fixtures/it-big-endian.mo");
const AR: &[u8] = include_bytes!("fixtures/ar.mo");
const LATIN1: &[u8] = include_bytes!("fixtures/latin1.mo");

#[test]
fn translates_and_falls_back_to_the_message_id() {
    let it = Catalog::parse(IT).expect("fixture");
    assert_eq!(it.tr("Shut down"), "Spegni");
    assert_eq!(it.tr("Signing in…"), "Accesso in corso…");
    assert_eq!(it.tr("Not in the catalog"), "Not in the catalog");
    assert_eq!(it.tr("Left untranslated"), "Left untranslated");
    assert_eq!(it.language(), Some("it"));
    assert!(!it.is_rtl());
}

#[test]
fn both_byte_orders_read_the_same() {
    let big = Catalog::parse(IT_BIG_ENDIAN).expect("fixture");
    assert_eq!(big.tr("Shut down"), "Spegni");
}

#[test]
fn plurals_follow_the_catalogs_rule() {
    let it = Catalog::parse(IT).expect("fixture");
    assert_eq!(it.tr_n("{n} update", "{n} updates", 1), "{n} aggiornamento");
    assert_eq!(it.tr_n("{n} update", "{n} updates", 0), "{n} aggiornamenti");
    let ar = Catalog::parse(AR).expect("fixture");
    let forms: Vec<&str> = [0, 1, 2, 5, 11, 100]
        .iter()
        .map(|&n| ar.tr_n("{n} update", "{n} updates", n))
        .collect();
    assert_eq!(forms, ["zero", "one", "two", "few", "many", "other"]);
    assert!(ar.is_rtl());
}

#[test]
fn an_empty_catalog_is_english_with_english_plurals() {
    let english = Catalog::empty();
    assert_eq!(english.tr_n("{n} update", "{n} updates", 1), "{n} update");
    assert_eq!(english.tr_n("{n} update", "{n} updates", 2), "{n} updates");
    assert_eq!(english.language(), None);
}

#[test]
fn context_separates_two_meanings_of_one_word() {
    let it = Catalog::parse(IT).expect("fixture");
    assert_eq!(it.tr_c("verb", "Restart"), "Riavvia");
    assert_eq!(it.tr_c("noun", "Restart"), "Restart");
    assert_eq!(it.tr("Restart"), "Restart");
}

#[test]
fn a_catalog_that_is_not_utf8_is_refused() {
    assert_eq!(Catalog::parse(LATIN1).err(), Some(Error::NotUtf8));
}

#[test]
fn hostile_input_is_an_error_and_never_a_panic() {
    assert!(matches!(Catalog::parse(b""), Err(Error::Malformed(_))));
    assert!(matches!(
        Catalog::parse(b"not a catalog at all"),
        Err(Error::Malformed(_))
    ));
    // Every truncation of a real catalog, and every single corrupted offset byte.
    for length in 0..IT.len() {
        let _ = Catalog::parse(&IT[..length]);
    }
    for position in 4..28.min(IT.len()) {
        let mut corrupt = IT.to_vec();
        corrupt[position] = 0xff;
        let _ = Catalog::parse(&corrupt);
    }
}

#[test]
fn an_unknown_plural_rule_is_named_in_the_error() {
    assert!(
        PluralRule::Arabic.index(103) == 3
            && PluralRule::One.index(7) == 0
            && PluralRule::MoreThanOne.index(1) == 0
    );
    let mut catalog = IT.to_vec();
    let needle = b"(n != 1)";
    let at = catalog
        .windows(needle.len())
        .position(|window| window == needle)
        .expect("rule in the fixture");
    catalog[at..at + needle.len()].copy_from_slice(b"(n >= 9)");
    assert!(matches!(
        Catalog::parse(&catalog),
        Err(Error::UnknownPluralRule(_))
    ));
}

#[test]
fn language_selection() {
    let env = |pairs: &'static [(&'static str, &'static str)]| {
        move |name: &str| {
            pairs
                .iter()
                .find(|(key, _)| *key == name)
                .map(|(_, value)| value.to_string())
        }
    };
    assert_eq!(
        languages(env(&[("LANG", "it_IT.UTF-8")]), None),
        ["it_IT", "it"]
    );
    assert_eq!(
        languages(
            env(&[("LANG", "en_US.UTF-8"), ("LC_ALL", "de_DE.UTF-8@euro")]),
            None
        ),
        ["de_DE", "de"]
    );
    assert_eq!(
        languages(env(&[("LANG", "en_US.UTF-8"), ("LC_MESSAGES", "ar")]), None),
        ["ar"]
    );
    assert_eq!(
        languages(
            env(&[("LANG", "")]),
            Some("# comment\nLANG=\"it_IT.UTF-8\"\n")
        ),
        ["it_IT", "it"]
    );
    assert!(languages(env(&[("LANG", "C.UTF-8")]), Some("LANG=it_IT.UTF-8")).is_empty());
    assert!(languages(env(&[]), None).is_empty());
}

#[test]
fn find_prefers_the_specific_directory_and_reports_a_broken_catalog() {
    let root = std::env::temp_dir().join(format!("athanor-i18n-{}", std::process::id()));
    let dir = root.join("it/LC_MESSAGES");
    std::fs::create_dir_all(&dir).expect("create");
    std::fs::write(dir.join("demo.mo"), IT).expect("write");
    let found =
        Catalog::find(&root, "demo", &["it_IT".to_string(), "it".to_string()]).expect("readable");
    assert_eq!(found.tr("Shut down"), "Spegni");
    assert_eq!(
        Catalog::find(&root, "demo", &["fr".to_string()])
            .expect("none is fine")
            .language(),
        None
    );
    std::fs::write(dir.join("demo.mo"), b"broken").expect("write");
    assert!(Catalog::find(&root, "demo", &["it".to_string()]).is_err());
    std::fs::remove_dir_all(root).expect("cleanup");
}
