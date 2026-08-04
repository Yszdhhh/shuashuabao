import React, { useState } from 'react';
import { Award, ChevronDown, ChevronUp, Layers, Crown } from 'lucide-react';
import { AppSettings, BossesResponse } from '../types';

interface ReputationCardProps {
  settings: AppSettings;
  onChange: (key: keyof AppSettings, value: any) => void;
  bosses: BossesResponse;
  disabled?: boolean;
}

export const ReputationCard: React.FC<ReputationCardProps> = ({
  settings,
  onChange,
  bosses,
  disabled = false,
}) => {
  const [isOpen, setIsOpen] = useState<boolean>(settings.auto_reputation);

  return (
    <div className="bg-[#151c2c] border border-[#243044] rounded-xl p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Award className="w-4 h-4 text-amber-400" />
          <span className="text-sm font-semibold text-amber-400">声望运行配置 (P1)</span>
          <span
            className={`text-xs px-2 py-0.5 rounded-full border ${
              settings.auto_reputation
                ? 'bg-amber-500/10 text-amber-300 border-amber-500/30'
                : 'bg-slate-700/20 text-slate-400 border-slate-700/40'
            }`}
          >
            {settings.auto_reputation ? '已开启' : '未开启'}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-300 font-medium">
            <input
              type="checkbox"
              checked={settings.auto_reputation}
              disabled={disabled}
              onChange={(e) => {
                onChange('auto_reputation', e.target.checked);
                if (e.target.checked) setIsOpen(true);
              }}
              className="w-4 h-4 rounded border-[#243044] bg-[#0b1220] text-blue-600 focus:ring-0"
            />
            <span>开启声望模式</span>
          </label>

          <button
            type="button"
            onClick={() => setIsOpen(!isOpen)}
            className="text-[#8b9bb4] hover:text-slate-200 p-1 rounded hover:bg-[#0b1220]"
          >
            {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {isOpen && (
        <div className="mt-4 pt-3 border-t border-[#243044] space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* 声望关卡 */}
            <div className="bg-[#0b1220] p-3 rounded-lg border border-[#243044]">
              <label className="text-xs font-medium text-[#8b9bb4] flex items-center gap-1.5 mb-2">
                <Layers className="w-3.5 h-3.5 text-amber-400" />
                <span>声望目标关卡 (reputation_stage1/2)</span>
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={settings.reputation_stage1}
                  disabled={disabled}
                  onChange={(e) =>
                    onChange('reputation_stage1', parseInt(e.target.value) || 1)
                  }
                  className="w-20 bg-[#151c2c] border border-[#243044] rounded px-3 py-1 text-xs text-white text-center"
                />
                <span className="text-slate-400 font-bold">—</span>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={settings.reputation_stage2}
                  disabled={disabled}
                  onChange={(e) =>
                    onChange('reputation_stage2', parseInt(e.target.value) || 10)
                  }
                  className="w-20 bg-[#151c2c] border border-[#243044] rounded px-3 py-1 text-xs text-white text-center"
                />
              </div>
            </div>

            {/* 继续声望开关 */}
            <div className="bg-[#0b1220] p-3 rounded-lg border border-[#243044] flex items-center justify-between">
              <div>
                <span className="text-xs font-medium text-slate-200 block">继续声望</span>
                <span className="text-[11px] text-[#8b9bb4]">当满足条件时自动循环推进声望</span>
              </div>
              <input
                type="checkbox"
                checked={settings.continue_reputation}
                disabled={disabled}
                onChange={(e) => onChange('continue_reputation', e.target.checked)}
                className="w-4 h-4 rounded border-[#243044] bg-[#0b1220] text-blue-600 focus:ring-0"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* 声望主线 Boss */}
            <div className="bg-[#0b1220] p-3 rounded-lg border border-[#243044]">
              <label className="text-xs font-medium text-[#8b9bb4] flex items-center gap-1.5 mb-1.5">
                <Crown className="w-3.5 h-3.5 text-purple-400" />
                <span>声望主线 Boss (reputation_sgzx_boss)</span>
              </label>
              <select
                value={settings.reputation_sgzx_boss}
                disabled={disabled}
                onChange={(e) => onChange('reputation_sgzx_boss', e.target.value)}
                className="w-full bg-[#151c2c] border border-[#243044] rounded px-3 py-1.5 text-xs text-slate-100 font-medium focus:border-blue-500"
              >
                <option value="">跟随主线 Boss</option>
                {bosses.main.map((b) => (
                  <option key={b.name} value={b.name}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>

            {/* 声望传家宝 Boss */}
            <div className="bg-[#0b1220] p-3 rounded-lg border border-[#243044]">
              <label className="text-xs font-medium text-[#8b9bb4] flex items-center gap-1.5 mb-1.5">
                <Crown className="w-3.5 h-3.5 text-emerald-400" />
                <span>声望传家宝 Boss (reputation_cjb_boss)</span>
              </label>
              <select
                value={settings.reputation_cjb_boss}
                disabled={disabled}
                onChange={(e) => onChange('reputation_cjb_boss', e.target.value)}
                className="w-full bg-[#151c2c] border border-[#243044] rounded px-3 py-1.5 text-xs text-slate-100 font-medium focus:border-blue-500"
              >
                <option value="">跟随传家宝 Boss</option>
                {bosses.cjb.map((b) => (
                  <option key={b.name} value={b.name}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
