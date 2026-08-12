import React, { useState, useEffect, useRef } from 'react';
import { Header } from './components/Header';
import { StatusCard } from './components/StatusCard';
import { RegularConfigCard } from './components/RegularConfigCard';
import { ReputationCard } from './components/ReputationCard';
import { SkillsGrid } from './components/SkillsGrid';
import { FettersCard } from './components/FettersCard';
import { EnvironmentCard } from './components/EnvironmentCard';
import { AdvancedSettingsCard } from './components/AdvancedSettingsCard';
import { ActionBar } from './components/ActionBar';
import { LogConsole } from './components/LogConsole';
import { AppSettings, BossesResponse, SkillOption, RunStatus, LogItem } from './types';
import { CheckCircle2, AlertCircle } from 'lucide-react';

const API_BASE = '/api';

export const App: React.FC = () => {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [status, setStatus] = useState<RunStatus>({
    running: false,
    phase: 'BOOT',
    phase_name: '就绪',
    game_count: 0,
    last_error: null,
    log_count: 0,
  });
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [skillsOptions, setSkillsOptions] = useState<SkillOption[]>([]);
  const [bossesOptions, setBossesOptions] = useState<BossesResponse>({ main: [], cjb: [] });
  
  const [loadingSync, setLoadingSync] = useState<boolean>(false);
  const [loadingSave, setLoadingSave] = useState<boolean>(false);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  const lastLogIdRef = useRef<number>(0);

  // 显示 Toast 提示
  const showToast = (message: string, type: 'success' | 'error' = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  // 初始化获取 Settings 与 选项
  useEffect(() => {
    fetchSettings();
    fetchOptions();
  }, []);

  // 轮询运行状态与增量日志
  useEffect(() => {
    const interval = setInterval(() => {
      fetchStatus();
      fetchLogs();
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const fetchSettings = async () => {
    try {
      const res = await fetch(`${API_BASE}/settings`);
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      const data = await res.json();
      setSettings(data);
    } catch (e) {
      console.error('Failed to load settings', e);
      showToast('获取配置失败，请确认后端 API 已启动', 'error');
    }
  };

  const fetchOptions = async () => {
    try {
      const [skRes, bossRes] = await Promise.all([
        fetch(`${API_BASE}/options/skills`),
        fetch(`${API_BASE}/options/bosses`),
      ]);
      if (skRes.ok) {
        setSkillsOptions(await skRes.json());
      }
      if (bossRes.ok) {
        setBossesOptions(await bossRes.json());
      }
    } catch (e) {
      console.error('Failed to load options', e);
    }
  };

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API_BASE}/run/status`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch (e) {
      // 忽略后端短暂不可用
    }
  };

  const fetchLogs = async () => {
    try {
      const res = await fetch(`${API_BASE}/run/logs?since=${lastLogIdRef.current}`);
      if (res.ok) {
        const data = await res.json();
        if (data.logs && data.logs.length > 0) {
          setLogs((prev) => [...prev, ...data.logs]);
          lastLogIdRef.current = data.next_since;
        }
      }
    } catch (e) {
      // 忽略
    }
  };

  const handleSettingChange = (key: keyof AppSettings, value: any) => {
    if (!settings) return;
    setSettings({
      ...settings,
      [key]: value,
    });
  };

  const handleSaveSettings = async () => {
    if (!settings) return;
    setLoadingSave(true);
    try {
      const res = await fetch(`${API_BASE}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = await res.json();
      setSettings(updated);
      showToast('配置已成功保存到 config/default_settings.json');
    } catch (e) {
      showToast(`保存配置失败: ${e}`, 'error');
    } finally {
      setLoadingSave(false);
    }
  };

  const handleSyncOfficial = async () => {
    setLoadingSync(true);
    try {
      const res = await fetch(`${API_BASE}/settings/sync-official`, {
        method: 'POST',
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const synced = await res.json();
      setSettings(synced);
      showToast('已成功从官方 %AppData%\\GameScript\\Settings\\Settings.json 同步配置');
    } catch (e: any) {
      showToast(`同步失败: ${e.message}`, 'error');
    } finally {
      setLoadingSync(false);
    }
  };

  const handleStartRun = async (maxSteps: number) => {
    if (!settings) return;
    // 先自动保存当前修改
    await handleSaveSettings();
    try {
      const res = await fetch(`${API_BASE}/run/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dry_run: settings.dry_run,
          max_steps: maxSteps > 0 ? maxSteps : null,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      showToast('刷图任务已成功启动！');
      fetchStatus();
    } catch (e: any) {
      showToast(`启动失败: ${e.message}`, 'error');
    }
  };

  const handleStopRun = async () => {
    try {
      await fetch(`${API_BASE}/run/stop`, { method: 'POST' });
      showToast('已向后端发送停止请求');
      fetchStatus();
    } catch (e: any) {
      showToast(`停止请求失败: ${e.message}`, 'error');
    }
  };

  if (!settings) {
    return (
      <div className="min-h-screen bg-[#0b1220] flex items-center justify-center text-slate-300">
        <div className="flex items-center gap-3 bg-[#151c2c] border border-[#243044] px-6 py-4 rounded-xl shadow-lg">
          <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm font-medium">正在加载刷刷宝控制面板与配置...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0b1220] text-[#e8eef8] pb-12">
      {/* Toast 提示浮窗 */}
      {toast && (
        <div
          className={`fixed top-4 right-4 z-50 px-4 py-2.5 rounded-xl shadow-2xl border text-xs font-medium flex items-center gap-2 transition-all transform animate-bounce ${
            toast.type === 'success'
              ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-200'
              : 'bg-red-500/20 border-red-500/50 text-red-200'
          }`}
        >
          {toast.type === 'success' ? (
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          ) : (
            <AlertCircle className="w-4 h-4 text-red-400" />
          )}
          <span>{toast.message}</span>
        </div>
      )}

      {/* 顶栏 */}
      <Header status={status} />

      {/* 主体区域 */}
      <main className="max-w-6xl mx-auto px-4 pt-4 space-y-4">
        {/* L0 / L1 运行说明 Banner */}
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-3.5 text-xs text-slate-300 flex items-start gap-2.5">
          <AlertCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-0.5">
            <p className="font-semibold text-amber-300">
              【大厅 → 房间 → 选关】：脚本会按页面状态识别创建房间、填写配置、点击房间开始，再识别目标关卡并点击棕色开始按钮。
            </p>
            <p className="text-slate-400">
              提示：自动建房需打开下方 L0 开关；同名大厅/房间会按页面锚点选择；Dry-run 只打印坐标不真实点击。地图颜色兜底若只有一个蓝色候选、弹窗输入框识别不安全或窗口被完全遮挡时会停住，不要降低阈值盲点。
            </p>
          </div>
        </div>

        {/* 状态看板 */}
        <StatusCard status={status} />

        {/* 核心配置与操作分区 */}
        <div className="grid grid-cols-1 gap-4">
          {/* 常规配置 P0 */}
          <RegularConfigCard
            settings={settings}
            onChange={handleSettingChange}
            bosses={bossesOptions}
            disabled={status.running}
          />

          {/* 主要技能下拉选择 (4项) */}
          <SkillsGrid
            skills={settings.skills}
            onChange={(skills) => handleSettingChange('skills', skills)}
            availableSkills={skillsOptions}
            disabled={status.running}
          />

          {/* 羁绊/卡牌下拉选择 (4项) */}
          <FettersCard
            settings={settings}
            onChange={handleSettingChange}
            disabled={status.running}
          />

          {/* 声望配置 P1 (折叠) */}
          <ReputationCard
            settings={settings}
            onChange={handleSettingChange}
            bosses={bossesOptions}
            disabled={status.running}
          />

          {/* 环境与 Dry-run */}
          <EnvironmentCard
            settings={settings}
            onChange={handleSettingChange}
            disabled={status.running}
          />

          {/* 高级运维 P2 */}
          <AdvancedSettingsCard
            settings={settings}
            onChange={handleSettingChange}
            disabled={status.running}
          />

          {/* 主操作控制按钮区 */}
          <ActionBar
            status={status}
            dryRun={settings.dry_run}
            onSyncOfficial={handleSyncOfficial}
            onSaveLocal={handleSaveSettings}
            onStart={handleStartRun}
            onStop={handleStopRun}
            loadingSync={loadingSync}
            loadingSave={loadingSave}
          />

          {/* 运行控制台日志 */}
          <LogConsole logs={logs} onClear={() => setLogs([])} />
        </div>
      </main>
    </div>
  );
};

export default App;
