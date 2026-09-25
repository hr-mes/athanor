//! Who may call `os.athanor.Notifications1` (doc_bar.md BR1): a process in the cgroup of
//! athanor-bar.service, read from the caller's credentials on the bus. Informative, as the
//! shield is: a process running as the user can replace that unit.

use std::fs;
use std::path::PathBuf;

pub const BAR_UNIT: &str = "athanor-bar.service";

#[derive(Debug, Clone)]
pub struct BarUnit {
    unit: String,
    proc_root: PathBuf,
}

impl BarUnit {
    #[must_use]
    pub fn from_proc() -> BarUnit {
        BarUnit::with_proc_root(BAR_UNIT, "/proc")
    }

    /// Reads `<proc_root>/<pid>/cgroup`. Tests point it at a directory of their own.
    #[must_use]
    pub fn with_proc_root(unit: &str, proc_root: impl Into<PathBuf>) -> BarUnit {
        BarUnit {
            unit: unit.to_owned(),
            proc_root: proc_root.into(),
        }
    }

    #[must_use]
    pub fn unit(&self) -> &str {
        &self.unit
    }

    #[must_use]
    pub fn admits(&self, pid: u32) -> bool {
        match fs::read_to_string(self.proc_root.join(pid.to_string()).join("cgroup")) {
            Ok(text) => unit_of(&text) == Some(self.unit.as_str()),
            Err(err) => {
                tracing::warn!(pid, error = %err, "cannot read the caller's cgroup; refused");
                false
            }
        }
    }
}

/// The last component of the unified hierarchy's (`0::`) path: the unit or scope the process
/// runs in. `None` at the root, or with no unified hierarchy.
#[must_use]
pub fn unit_of(cgroup: &str) -> Option<&str> {
    cgroup
        .lines()
        .find_map(|line| line.strip_prefix("0::"))
        .and_then(|path| path.trim_end().rsplit('/').next())
        .filter(|unit| !unit.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;

    const BAR: &str =
        "0::/user.slice/user-1000.slice/user@1000.service/app.slice/athanor-bar.service\n";

    #[test]
    fn the_unit_is_the_last_component_of_the_unified_path() {
        assert_eq!(unit_of(BAR), Some("athanor-bar.service"));
        assert_eq!(unit_of("0::/\n"), None);
        assert_eq!(
            unit_of("1:name=systemd:/user.slice/athanor-bar.service\n"),
            None,
            "v1 only"
        );
    }

    #[test]
    fn only_the_bar_unit_is_admitted() {
        let root =
            std::env::temp_dir().join(format!("athanor-shelld-sender-{}", std::process::id()));
        for (pid, cgroup) in [
            (10, BAR),
            (11, "0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-athanor-foo@0123.service\n"),
            (12, "0::/user.slice/user-1000.slice/user@1000.service/app.slice/athanor-bar.service/sub\n"),
        ] {
            fs::create_dir_all(root.join(pid.to_string())).expect("mkdir");
            fs::write(root.join(pid.to_string()).join("cgroup"), cgroup).expect("write");
        }
        let bar = BarUnit::with_proc_root(BAR_UNIT, &root);
        assert!(bar.admits(10));
        assert!(!bar.admits(11), "an application the bar launched");
        assert!(!bar.admits(12), "a child cgroup");
        assert!(!bar.admits(13), "no such process");
        fs::remove_dir_all(root).expect("cleanup");
    }
}
