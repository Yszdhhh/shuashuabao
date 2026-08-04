import React, { useState } from 'react';
import { Play, Square, RefreshCw, Save, AlertTriangle, ShieldCheck } from 'lucide-react';
import { RunStatus } from '../types';

interface ActionBarProps {
  status: RunStatus;
  dryRun: boolean;
  onSyncOfficial: () => void;
  onSaveLocal: () => void;
  onStart: (maxSteps: number) => void;
  onStop: () => void;
  loadingSync?: boolean;
  loadingSave?: boolean;
}

export const ActionBar: React.FC<ActionBarProps> = ({
  status,
  dryRun,
  onSyncOfficial,
  onSaveLocal,
  onStart,
  onStop,
  loadingSync = false,
  loadingSave = false,
}) => {
  const [maxSteps, setMaxSteps] = useState<number>(0);
  const [showConfirmModal, setShowConfirmModal] = useState<boolean>(false);

  const handleStartClick = () => {
    if (!dryRun) {
      setShowConfirmModal(true);
    } else {
      onStart(maxSteps);
    }
  };

  const confirmStartReal = () => {
    setShowConfirmModal(false);
    onStart(maxSteps);
  };

  return (
    <div className="bg-[#151c2c] border border-[#243044] rounded-xl p-4 shadow-md space-y-3">
      {/* 辅助按钮栏 */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#243044] pb-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onSyncOfficial}
            disabled={status.running || loadingSync}
            className="px-3 py-1.5 bg-[#0b1220] border border-blue-500/40 text-blue-300 hover:bg-blue-600/20 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-all disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loadingSync ? 'animate-spin' : ''}`} />
            <span>从官方 Settings 同步</span>
          </button>

          <button
            type="button"
            onClick={onSaveLocal}
            disabled={status.running || loadingSave}
            className="px-3 py-1.5 bg-[#0b1220] border border-[#243044] text-slate-200 hover:border-slate-500 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-all disabled:opacity-50"
          >
            <Save className="w-3.5 h-3.5 text-emerald-400" />
            <span>保存配置 (Save)</span>
          </button>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="text-[#8b9bb4]">测试限制步数:</span>
          <input
            type="number"
            min={0}
            max={99999}
            value={maxSteps}
            disabled={status.running}
            onChange={(e) => setMaxSteps(parseInt(e.target.value) || 0)}
            placeholder="0=无限"
            className="w-20 bg-[#0b1220] border border-[#243044] rounded px-2 py-1 text-white text-center font-mono focus:border-blue-500"
          />
          <span className="text-[11px] text-[#8b9bb4]">(0 = 持续运行)</span>
        </div>
      </div>

      {/* 主按钮区 */}
      <div>
        {status.running ? (
          <button
            type="button"
            onClick={onStop}
            className="w-full py-3.5 bg-gradient-to-r from-red-600 to-rose-700 hover:from-red-500 hover:to-rose-600 text-white font-bold text-base rounded-xl shadow-lg shadow-red-900/30 flex items-center justify-center gap-2 tracking-wider transition-all transform active:scale-[0.99]"
          >
            <Square className="w-5 h-5 fill-current" />
            <span>停  止  游  戏  任  务</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={handleStartClick}
            className="w-full py-3.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-bold text-base rounded-xl shadow-lg shadow-blue-900/30 flex items-center justify-center gap-2 tracking-wider transition-all transform active:scale-[0.99]"
          >
            <Play className="w-5 h-5 fill-current" />
            <span>开  始  游  戏  (独狼刷图)</span>
          </button>
        )}
      </div>

      {/* 真机二次确认 Alert Modal */}
      {showConfirmModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-[#151c2c] border border-amber-500/50 rounded-2xl max-w-md w-full p-5 shadow-2xl space-y-4">
            <div className="flex items-center gap-3 text-amber-400">
              <AlertTriangle className="w-7 h-7 shrink-0" />
              <h3 className="text-base font-bold">准备发起真机模拟点击</h3>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              您当前关闭了 <b className="text-amber-300">Dry-run</b> 演示模式！
              启动后脚本将开始向标题包含 <b className="text-blue-300">“英雄三国”</b> 的窗口发送真实的鼠标点击与键盘输入。
            </p>

            <div className="p-3 bg-[#0b1220] rounded-lg border border-[#243044] text-[11px] text-[#8b9bb4]">
              提示：若需要急停，可按键盘快捷键 <kbd className="px-1.5 py-0.5 bg-[#151c2c] text-white border border-[#243044] rounded">Shift + F12</kbd> 或在此面板点击“停止”。
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowConfirmModal(false)}
                className="px-4 py-2 bg-[#0b1220] border border-[#243044] text-slate-300 rounded-lg text-xs font-medium hover:bg-[#151c2c]"
              >
                取消
              </button>
              <button
                type="button"
                onClick={confirmStartReal}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold shadow"
              >
                确认开始真机运行
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
