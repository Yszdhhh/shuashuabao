import React from 'react';
import { Activity, AlertTriangle, Layers, RotateCw, CheckCircle2 } from 'lucide-react';
import { RunStatus } from '../types';

interface StatusCardProps {
  status: RunStatus;
}

export const StatusCard: React.FC<StatusCardProps> = ({ status }) => {
  const getPhaseBadge = (phase: string, phaseName: string) => {
    switch (phase) {
      case 'MAIN_LINE':
        return 'bg-blue-500/20 text-blue-300 border-blue-500/40';
      case 'LONGZHU':
        return 'bg-purple-500/20 text-purple-300 border-purple-500/40';
      case 'ANCHOR_BOSS':
        return 'bg-amber-500/20 text-amber-300 border-amber-500/40';
      case 'QUIT':
      case 'NEXT':
        return 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40';
      default:
        return 'bg-slate-700/30 text-slate-300 border-slate-600/40';
    }
  };

  return (
    <div className="bg-[#151c2c] border border-[#243044] rounded-xl p-4 shadow-sm">
      <div className="flex items-center justify-between border-b border-[#243044] pb-2.5 mb-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-blue-400">
          <Activity className="w-4 h-4" />
          <span>运行状态看板</span>
        </div>
        <div className="text-xs text-[#8b9bb4]">
          快捷键: <kbd className="px-1.5 py-0.5 bg-[#0b1220] border border-[#243044] rounded text-slate-300 font-mono">Shift + F12</kbd> 急停
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {/* 当前局数 */}
        <div className="bg-[#0b1220] border border-[#243044] rounded-lg p-3 flex items-center justify-between">
          <div>
            <div className="text-xs text-[#8b9bb4] flex items-center gap-1 mb-1">
              <RotateCw className="w-3.5 h-3.5 text-blue-400" />
              <span>当前局数</span>
            </div>
            <div className="text-2xl font-bold text-white tracking-tight">
              {status.game_count} <span className="text-xs font-normal text-[#8b9bb4]">局</span>
            </div>
          </div>
          <div className="w-10 h-10 rounded-full bg-blue-600/10 border border-blue-500/20 flex items-center justify-center text-blue-400 font-bold">
            #{status.game_count}
          </div>
        </div>

        {/* 当前阶段 */}
        <div className="bg-[#0b1220] border border-[#243044] rounded-lg p-3 flex items-center justify-between">
          <div>
            <div className="text-xs text-[#8b9bb4] flex items-center gap-1 mb-1">
              <Layers className="w-3.5 h-3.5 text-purple-400" />
              <span>当前阶段</span>
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span
                className={`text-xs px-2.5 py-1 rounded-md border font-semibold ${getPhaseBadge(
                  status.phase,
                  status.phase_name
                )}`}
              >
                {status.phase} {status.phase_name}
              </span>
            </div>
          </div>
          <div className="w-10 h-10 rounded-full bg-purple-600/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
            <CheckCircle2 className="w-5 h-5" />
          </div>
        </div>

        {/* 状态总览 */}
        <div className="bg-[#0b1220] border border-[#243044] rounded-lg p-3 flex items-center justify-between">
          <div>
            <div className="text-xs text-[#8b9bb4] flex items-center gap-1 mb-1">
              <Activity className="w-3.5 h-3.5 text-emerald-400" />
              <span>运行模式</span>
            </div>
            <div className="text-sm font-semibold text-slate-200">
              单机/自己刷图
            </div>
          </div>
          <div className="text-xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 px-2 py-1 rounded">
            正常就绪
          </div>
        </div>
      </div>

      {/* 错误警报 */}
      {status.last_error && (
        <div className="mt-3 bg-red-500/10 border border-red-500/30 rounded-lg p-2.5 flex items-start gap-2 text-xs text-red-300">
          <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold text-red-200">最近错误提示：</span>
            {status.last_error}
          </div>
        </div>
      )}
    </div>
  );
};
