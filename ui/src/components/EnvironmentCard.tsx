import React from 'react';
import { Monitor, ShieldAlert, Sliders, Info } from 'lucide-react';
import { AppSettings } from '../types';

interface EnvironmentCardProps {
  settings: AppSettings;
  onChange: (key: keyof AppSettings, value: any) => void;
  disabled?: boolean;
}

export const EnvironmentCard: React.FC<EnvironmentCardProps> = ({
  settings,
  onChange,
  disabled = false,
}) => {
  return (
    <div className="bg-[#151c2c] border border-[#243044] rounded-xl p-4 shadow-sm">
      <div className="flex items-center justify-between border-b border-[#243044] pb-2.5 mb-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-blue-400">
          <Monitor className="w-4 h-4" />
          <span>环境与匹配设置</span>
        </div>
        <span className="text-xs text-[#8b9bb4]">锁窗、学习模式与匹配阈值</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* 窗口标题匹配 */}
        <div className="bg-[#0b1220] p-3 rounded-lg border border-[#243044]">
          <label className="text-xs font-medium text-[#8b9bb4] flex items-center gap-1.5 mb-1.5">
            <Monitor className="w-3.5 h-3.5 text-blue-400" />
            <span>游戏窗口标题包含 (window_title_contains)</span>
          </label>
          <input
            type="text"
            value={settings.window_title_contains}
            disabled={disabled}
            onChange={(e) => onChange('window_title_contains', e.target.value)}
            placeholder="例如: 英雄三国"
            className="w-full bg-[#151c2c] border border-[#243044] rounded px-3 py-1.5 text-xs text-white focus:border-blue-500 focus:outline-none"
          />
        </div>

        {/* 学习模式（底层 settings.dry_run） */}
        <div className="bg-[#0b1220] p-3 rounded-lg border border-[#243044] flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <label className="text-xs font-medium text-slate-200 flex items-center gap-1.5">
              <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
              <span>学习模式（只观察记录）</span>
            </label>
            <input
              type="checkbox"
              checked={settings.dry_run}
              disabled={disabled}
              onChange={(e) => onChange('dry_run', e.target.checked)}
              className="w-4 h-4 rounded border-[#243044] bg-[#151c2c] text-blue-600 focus:ring-0 cursor-pointer"
            />
          </div>

          <p className="text-[11px] text-[#8b9bb4] mt-1">
            {settings.dry_run ? (
              <span className="text-amber-400">只观察/记录决策，不实操；写入本机 learning 日志供自适应调参。</span>
            ) : (
              <span className="text-emerald-400">真机模式：将对游戏窗口发起自动化点击。</span>
            )}
          </p>
        </div>

        {/* OpenCV 找图阈值 */}
        <div className="bg-[#0b1220] p-3 rounded-lg border border-[#243044]">
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs font-medium text-[#8b9bb4] flex items-center gap-1.5">
              <Sliders className="w-3.5 h-3.5 text-purple-400" />
              <span>找图相似度阈值 (match_threshold)</span>
            </label>
            <span className="text-xs font-mono font-bold text-purple-300">
              {settings.match_threshold.toFixed(2)}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="range"
              min={0.5}
              max={0.99}
              step={0.01}
              value={settings.match_threshold}
              disabled={disabled}
              onChange={(e) => onChange('match_threshold', parseFloat(e.target.value))}
              className="w-full h-1.5 bg-[#151c2c] rounded-lg appearance-none cursor-pointer accent-purple-500"
            />
          </div>
        </div>
      </div>

      {/* 提示条 */}
      <div className="mt-3 p-2.5 bg-blue-500/10 border border-blue-500/20 rounded-lg flex items-center gap-2 text-xs text-blue-300">
        <Info className="w-4 h-4 text-blue-400 shrink-0" />
        <span>建议环境配置：请将游戏客户端设置为 <b>窗口化 1600 × 900</b> 像素分辨率，Windows 缩放比设置为 100% 以获得最佳图像匹配准确度。</span>
      </div>
    </div>
  );
};
