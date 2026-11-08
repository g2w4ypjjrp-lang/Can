//! İşlem motoru gözetmeni.
//!
//! * Motor, kurulumla gelen `engine/ati-engine(.exe)` klasöründen (veya geliştirmede
//!   `ATI_ENGINE_EXE` ortam değişkenindeki komuttan) başlatılır.
//! * Her açılışta rastgele bir oturum belirteci üretilir ve motora `ATI_LOCAL_API_TOKEN` ortam
//!   değişkeniyle verilir; belirteç diske yazılmaz. Motor yalnızca 127.0.0.1'i dinler.
//! * Motor çökerse artan beklemeyle yeniden başlatılır (10 dakikada en fazla 5 kez).
//! * Uygulama kapanırken motora `POST /v1/engine/shutdown` gönderilir; en fazla 20 saniye düzgün
//!   kapanması beklenir, sonra süreç sonlandırılır.
//! * Windows'ta motor bir iş nesnesine (job object) bağlanır: kabuk beklenmedik biçimde kapanırsa
//!   işletim sistemi motoru da kapatır (sahipsiz motor kalmaz).

use std::fs::{self, File};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

const HEALTH_TIMEOUT: Duration = Duration::from_secs(120);
const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(20);
const MAX_RESTARTS: usize = 5;
const RESTART_WINDOW: Duration = Duration::from_secs(600);

#[derive(Clone, serde::Serialize)]
pub struct Connection {
    pub base_url: String,
    pub token: String,
}

#[derive(Clone, serde::Serialize, Default)]
pub struct EngineInfo {
    pub state: String, // starting | running | restarting | failed | stopped | external
    pub restarts: usize,
    pub error: Option<String>,
    pub log_file: Option<String>,
}

struct Inner {
    child: Option<Child>,
    info: EngineInfo,
    restart_times: Vec<Instant>,
    stopping: bool,
}

pub struct Engine {
    port: u16,
    token: String,
    command: Option<(PathBuf, Vec<String>)>,
    log_dir: PathBuf,
    inner: Mutex<Inner>,
    #[cfg(windows)]
    job: job::Job,
}

pub fn random_token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("işletim sistemi rastgele sayı üretemedi");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn free_port() -> std::io::Result<u16> {
    let listener = TcpListener::bind(("127.0.0.1", 0))?;
    Ok(listener.local_addr()?.port())
}

/// Basit HTTP/1.1 isteği (yalnızca 127.0.0.1). Durum kodunu döner.
fn http(port: u16, method: &str, path: &str, token: Option<&str>) -> std::io::Result<u16> {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_secs(2))?;
    stream.set_read_timeout(Some(Duration::from_secs(5)))?;
    let auth = token
        .map(|t| format!("Authorization: Bearer {t}\r\n"))
        .unwrap_or_default();
    write!(
        stream,
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n{auth}Content-Length: 0\r\nConnection: close\r\n\r\n"
    )?;
    let mut head = [0u8; 64];
    let n = stream.read(&mut head)?;
    let text = String::from_utf8_lossy(&head[..n]);
    text.split_whitespace()
        .nth(1)
        .and_then(|code| code.parse().ok())
        .ok_or_else(|| std::io::Error::other("geçersiz HTTP yanıtı"))
}

fn tail(path: &Path, max: usize) -> String {
    fs::read_to_string(path)
        .map(|s| {
            let start = s.len().saturating_sub(max);
            let start = (start..s.len())
                .find(|i| s.is_char_boundary(*i))
                .unwrap_or(s.len());
            s[start..].to_string()
        })
        .unwrap_or_default()
}

impl Engine {
    /// `external`: geliştirmede zaten çalışan bir motora bağlanmak için (ATI_ENGINE_URL/TOKEN).
    pub fn new(
        command: Option<(PathBuf, Vec<String>)>,
        log_dir: PathBuf,
        port: Option<u16>,
        token: Option<String>,
    ) -> std::io::Result<Arc<Self>> {
        fs::create_dir_all(&log_dir)?;
        let external = command.is_none();
        Ok(Arc::new(Self {
            port: match port {
                Some(p) => p,
                None => free_port()?,
            },
            token: token.unwrap_or_else(random_token),
            command,
            log_dir,
            inner: Mutex::new(Inner {
                child: None,
                info: EngineInfo {
                    state: if external {
                        "external".into()
                    } else {
                        "starting".into()
                    },
                    ..Default::default()
                },
                restart_times: Vec::new(),
                stopping: false,
            }),
            #[cfg(windows)]
            job: job::Job::new(),
        }))
    }

    pub fn connection(&self) -> Connection {
        Connection {
            base_url: format!("http://127.0.0.1:{}", self.port),
            token: self.token.clone(),
        }
    }

    pub fn info(&self) -> EngineInfo {
        self.inner.lock().unwrap().info.clone()
    }

    fn log_file(&self) -> PathBuf {
        self.log_dir.join("engine-console.log")
    }

    fn spawn(&self) -> std::io::Result<Child> {
        let (exe, prefix) = self
            .command
            .as_ref()
            .ok_or_else(|| std::io::Error::other("harici motor"))?;
        let log = File::create(self.log_file())?;
        let mut cmd = Command::new(exe);
        cmd.args(prefix)
            .args(["run", "--port", &self.port.to_string()])
            .env("ATI_LOCAL_API_TOKEN", &self.token)
            .env("PYTHONUTF8", "1")
            .stdin(Stdio::null())
            .stdout(log.try_clone()?)
            .stderr(log);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        let child = cmd.spawn()?;
        #[cfg(windows)]
        self.job.assign(&child);
        Ok(child)
    }

    /// Motoru başlatır ve sağlık denetimi geçene kadar bekler.
    pub fn start(&self) -> Result<(), String> {
        if self.command.is_none() {
            return self.wait_healthy(None);
        }
        let child = self
            .spawn()
            .map_err(|e| format!("Motor başlatılamadı: {e}"))?;
        {
            let mut inner = self.inner.lock().unwrap();
            inner.child = Some(child);
            inner.info.state = "starting".into();
            inner.info.log_file = Some(self.log_file().display().to_string());
        }
        match self.wait_healthy(Some(())) {
            Ok(()) => {
                let mut inner = self.inner.lock().unwrap();
                inner.info.state = "running".into();
                inner.info.error = None;
                Ok(())
            }
            Err(e) => {
                let mut inner = self.inner.lock().unwrap();
                inner.info.state = "failed".into();
                inner.info.error = Some(e.clone());
                Err(e)
            }
        }
    }

    fn wait_healthy(&self, managed: Option<()>) -> Result<(), String> {
        let deadline = Instant::now() + HEALTH_TIMEOUT;
        loop {
            if let Ok(200) = http(self.port, "GET", "/v1/health", None) {
                return Ok(());
            }
            if managed.is_some() {
                let mut inner = self.inner.lock().unwrap();
                if let Some(child) = inner.child.as_mut() {
                    if let Ok(Some(status)) = child.try_wait() {
                        return Err(format!(
                            "Motor açılırken kapandı ({status}). Son günlük satırları:\n{}",
                            tail(&self.log_file(), 2000)
                        ));
                    }
                }
            }
            if Instant::now() > deadline {
                return Err("Motor zamanında hazır olmadı".into());
            }
            thread::sleep(Duration::from_millis(300));
        }
    }

    /// Çöken motoru yeniden başlatan gözetim döngüsü (ayrı iş parçacığında).
    pub fn supervise(self: &Arc<Self>) {
        if self.command.is_none() {
            return;
        }
        let engine = Arc::clone(self);
        thread::spawn(move || loop {
            thread::sleep(Duration::from_secs(2));
            let exited = {
                let mut inner = engine.inner.lock().unwrap();
                if inner.stopping {
                    return;
                }
                match inner.child.as_mut().map(|c| c.try_wait()) {
                    Some(Ok(Some(status))) => Some(status),
                    _ => None,
                }
            };
            let Some(status) = exited else { continue };
            let allowed = {
                let mut inner = engine.inner.lock().unwrap();
                let now = Instant::now();
                inner
                    .restart_times
                    .retain(|t| now.duration_since(*t) < RESTART_WINDOW);
                inner.child = None;
                if inner.restart_times.len() >= MAX_RESTARTS {
                    inner.info.state = "failed".into();
                    inner.info.error = Some(format!(
                        "Motor tekrar tekrar kapandı (son: {status}); günlüğe bakın"
                    ));
                    false
                } else {
                    inner.restart_times.push(now);
                    inner.info.restarts += 1;
                    inner.info.state = "restarting".into();
                    true
                }
            };
            if !allowed {
                return;
            }
            let wait = 2u64.pow(engine.info().restarts.min(5) as u32);
            thread::sleep(Duration::from_secs(wait));
            let _ = engine.start();
        });
    }

    /// Düzgün kapatma: önce motora kapanma isteği, süre dolarsa sonlandırma.
    pub fn shutdown(&self) {
        let child = {
            let mut inner = self.inner.lock().unwrap();
            inner.stopping = true;
            inner.info.state = "stopped".into();
            inner.child.take()
        };
        let Some(mut child) = child else { return };
        let _ = http(self.port, "POST", "/v1/engine/shutdown", Some(&self.token));
        let deadline = Instant::now() + SHUTDOWN_TIMEOUT;
        while Instant::now() < deadline {
            if let Ok(Some(_)) = child.try_wait() {
                return;
            }
            thread::sleep(Duration::from_millis(200));
        }
        let _ = child.kill();
        let _ = child.wait();
    }

    pub fn restart(&self) -> Result<(), String> {
        if self.command.is_none() {
            return Err("Harici motor yeniden başlatılamaz".into());
        }
        self.shutdown();
        self.inner.lock().unwrap().stopping = false;
        self.start()
    }
}

#[cfg(windows)]
mod job {
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;
    use windows_sys::Win32::Foundation::HANDLE;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    /// Kabuk kapanınca (çökme dahil) içindeki süreçleri sonlandıran iş nesnesi.
    pub struct Job(HANDLE);
    unsafe impl Send for Job {}
    unsafe impl Sync for Job {}

    impl Job {
        pub fn new() -> Self {
            unsafe {
                let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if !handle.is_null() {
                    let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                    SetInformationJobObject(
                        handle,
                        JobObjectExtendedLimitInformation,
                        &info as *const _ as *const core::ffi::c_void,
                        std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                    );
                }
                Job(handle)
            }
        }

        pub fn assign(&self, child: &Child) {
            if !self.0.is_null() {
                unsafe {
                    AssignProcessToJobObject(self.0, child.as_raw_handle() as HANDLE);
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn token_is_random_and_hex() {
        let a = random_token();
        let b = random_token();
        assert_eq!(a.len(), 64);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, b);
    }

    #[test]
    fn free_port_is_loopback_bindable() {
        let port = free_port().unwrap();
        assert!(port > 0);
        TcpListener::bind(("127.0.0.1", port)).unwrap();
    }

    #[test]
    fn tail_respects_char_boundaries() {
        let dir = std::env::temp_dir().join(format!("ati-tail-{}", random_token()));
        fs::create_dir_all(&dir).unwrap();
        let file = dir.join("log.txt");
        fs::write(&file, "çğüşıö satır sonu").unwrap();
        let text = tail(&file, 5);
        assert!(text.ends_with("sonu"));
        fs::remove_dir_all(dir).unwrap();
    }
}
