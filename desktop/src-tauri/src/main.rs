// Windows'ta sürüm derlemesinde ek konsol penceresi açılmaz.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod engine;

use std::path::PathBuf;
use std::sync::Arc;

use engine::{Connection, Engine, EngineInfo};
use tauri::{Manager, RunEvent, State};
use tauri_plugin_updater::UpdaterExt;

struct AppEngine(Arc<Engine>);

/// Arayüzün motor adresi ve oturum belirteci. Motor hazır değilse hata döner (arayüz yeniden dener).
#[tauri::command]
fn engine_connection(engine: State<'_, AppEngine>) -> Result<Connection, String> {
    let info = engine.0.info();
    match info.state.as_str() {
        "running" | "external" => Ok(engine.0.connection()),
        "failed" => Err(info.error.unwrap_or_else(|| "Motor başlatılamadı".into())),
        other => Err(format!("Motor hazır değil: {other}")),
    }
}

#[tauri::command]
fn engine_info(engine: State<'_, AppEngine>) -> EngineInfo {
    engine.0.info()
}

#[tauri::command]
async fn engine_restart(engine: State<'_, AppEngine>) -> Result<(), String> {
    let engine = Arc::clone(&engine.0);
    tauri::async_runtime::spawn_blocking(move || engine.restart())
        .await
        .map_err(|e| e.to_string())?
}

/// Motor komutu: geliştirmede `ATI_ENGINE_EXE` (ör. `uv` ve önek bağımsız değişkenleri
/// `ATI_ENGINE_ARGS`), kurulumda paketlenmiş `engine/ati-engine(.exe)`. `ATI_ENGINE_URL` ile
/// çalışan bir motora bağlanılırsa motor başlatılmaz.
fn engine_command(app: &tauri::AppHandle) -> Option<(PathBuf, Vec<String>)> {
    if std::env::var("ATI_ENGINE_PORT").is_ok() {
        return None;
    }
    if let Ok(exe) = std::env::var("ATI_ENGINE_EXE") {
        let args = std::env::var("ATI_ENGINE_ARGS")
            .map(|a| a.split_whitespace().map(String::from).collect())
            .unwrap_or_default();
        return Some((PathBuf::from(exe), args));
    }
    let name = if cfg!(windows) {
        "ati-engine.exe"
    } else {
        "ati-engine"
    };
    let dir = app.path().resource_dir().ok()?;
    Some((dir.join("engine").join(name), Vec::new()))
}

/// Otomatik güncelleme yapılandırılmış mı? Açık anahtar (sunucudaki güncelleme anahtarının açık
/// kısmı) sürüme gömülmeden güncelleme denetlenmez.
fn updater_configured(app: &tauri::AppHandle) -> bool {
    app.config()
        .plugins
        .0
        .get("updater")
        .and_then(|u| u.get("pubkey"))
        .and_then(|k| k.as_str())
        .is_some_and(|k| !k.trim().is_empty())
}

#[derive(serde::Serialize)]
struct UpdateInfo {
    version: String,
    notes: Option<String>,
}

#[tauri::command]
async fn check_update(app: tauri::AppHandle) -> Result<Option<UpdateInfo>, String> {
    if !updater_configured(&app) {
        return Ok(None);
    }
    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| format!("Güncelleme denetlenemedi: {e}"))?;
    Ok(update.map(|u| UpdateInfo {
        version: u.version.clone(),
        notes: u.body.clone(),
    }))
}

#[tauri::command]
async fn install_update(
    app: tauri::AppHandle,
    engine: tauri::State<'_, AppEngine>,
) -> Result<(), String> {
    if !updater_configured(&app) {
        return Err("Otomatik güncelleme bu sürümde yapılandırılmadı".into());
    }
    let update = app
        .updater()
        .map_err(|e| e.to_string())?
        .check()
        .await
        .map_err(|e| format!("Güncelleme denetlenemedi: {e}"))?
        .ok_or_else(|| "Yeni sürüm yok".to_string())?;
    // İmza indirme sırasında gömülü açık anahtarla doğrulanır; doğrulanmayan dosya kurulmaz.
    let bytes = update
        .download(|_, _| {}, || {})
        .await
        .map_err(|e| format!("Güncelleme indirilemedi ya da imzası doğrulanamadı: {e}"))?;
    // Motor kapatılır (dosyaları kilitli kalmasın); borsadaki stop emirleri yerinde kalır.
    engine.0.shutdown();
    update
        .install(bytes)
        .map_err(|e| format!("Güncelleme kurulamadı: {e}"))?;
    app.restart();
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // İkinci kez açılırsa mevcut pencere öne getirilir (ikinci motor başlatılmaz).
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .setup(|app| {
            let handle = app.handle().clone();
            let log_dir = handle.path().app_log_dir()?;
            let external_port = std::env::var("ATI_ENGINE_PORT")
                .ok()
                .and_then(|p| p.parse().ok());
            let external_token = std::env::var("ATI_ENGINE_TOKEN").ok();
            let engine = Engine::new(
                engine_command(&handle),
                log_dir,
                external_port,
                external_token,
            )?;
            app.manage(AppEngine(Arc::clone(&engine)));
            // Açılış pencereyi bekletmez: motor arka planda başlar, arayüz hazır olunca bağlanır.
            std::thread::spawn(move || {
                if engine.start().is_ok() {
                    engine.supervise();
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            engine_connection,
            engine_info,
            engine_restart,
            check_update,
            install_update
        ])
        .build(tauri::generate_context!())
        .expect("uygulama başlatılamadı")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(engine) = app.try_state::<AppEngine>() {
                    engine.0.shutdown();
                }
            }
        });
}
