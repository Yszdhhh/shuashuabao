import React from 'react';
import { ShieldCheck, MonitorPlay, Zap, AlertCircle } from 'lucide-react';
import { RunStatus } from '../types';

interface HeaderProps {
  status: RunStatus;
}

export const Header: React.FC<HeaderProps> = ({ status }) => {
  return (
    <header className="bg-[#151c2c] border-b border-[#243044] px-4 py-3 sticky top-0 z-30 shadow-md">
      <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="bg-blue-600/20 p-2 rounded-lg border border-blue-500/30 text-blue-400">
            <MonitorPlay className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-blue-400 tracking-wide">
                懒人系列之魔兽世界刷刷刷
              </h1>
              <span className="bg-blue-500/10 text-blue-400 border border-blue-500/30 text-xs px-2 py-0.5 rounded-full font-medium flex items-center gap-1">
                <Zap className="w-3 h-3" /> 本地 · 自己刷图
              </span>
            </div>
            <p className="text-xs text-[#8b9bb4]">
              刷刷宝 · 免证书 / 无网络依赖 / 独狼自动挂机
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs text-[#8b9bb4] bg-[#0b1220] px-2.5 py-1 rounded-md border border-[#243044]">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span>本地授权: 已启用</span>
          </div>

          <div
            className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-semibold shadow-sm transition-all ${
              status.running
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/40 animate-pulse'
                : status.last_error
                ? 'bg-red-500/10 text-red-400 border-red-500/40'
                : 'bg-slate-700/20 text-slate-400 border-slate-700/50'
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                status.running
                  ? 'bg-emerald-400 animate-ping'
                  : status.last_error
                  ? 'bg-red-400'
                  : 'bg-slate-500'
              }`}
            />
            <span>
              {status.running
                ? `运行中 (${status.phase_name})`
                : status.last_error
                ? '出 错'
                : '空 闲'}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
};
