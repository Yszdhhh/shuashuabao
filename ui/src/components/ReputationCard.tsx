import React, { useState } from 'react';
import { Award, ChevronDown, ChevronUp, Shield, Flame, Compass, Zap, Crown, Skull, Info } from 'lucide-react';
import { AppSettings, BossesResponse } from '../types';

interface ReputationCardProps {
  settings: AppSettings;
  onChange: (key: keyof AppSettings, value: any) => void;
  bosses?: BossesResponse;
  disabled?: boolean;
}

export const REPUTATION_OPTIONS = [
  { id: 1, name: '黑锋骑士团', desc: '怪物强度 / 血量提升', icon: Skull, color: 'text-purple-400 border-purple-500/40 bg-purple-500/10' },
  { id: 2, name: '银色北伐军', desc: '怪物防御 / 恢复加成', icon: Shield, color: 'text-blue-400 border-blue-500/40 bg-blue-500/10' },
  { id: 3, name: '肯瑞托', desc: '玩家伤害 / 恢复衰减', icon: Zap, color: 'text-indigo-400 border-indigo-500/40 bg-indigo-500/10' },
  { id: 4, name: '探险者协会', desc: '玩家力量 / 攻击压制', icon: Compass, color: 'text-amber-400 border-amber-500/40 bg-amber-500/10' },
  { id: 5, name: '元素领主', desc: '元素Debuff / 强化攻击', icon: Flame, color: 'text-red-400 border-red-500/40 bg-red-500/10' },
  { id: 6, name: '守护巨龙', desc: '终极强度 / 巨龙压制', icon: Crown, color: 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10' },
];

export const ReputationCard: React.FC<ReputationCardProps> = ({
  settings,
  onChange,
  disabled = false,
}) => {
  const [isOpen, setIsOpen] = useState<boolean>(settings.auto_reputation);
  const currentRepId = settings.reputation_type || 1;
  const currentLevel = settings.reputation_level || 1;

  return (
    <div className="bg-[#151c2c] border border-[#243044] rounded-xl p-4 shadow-sm space-y-3">
      {/* 头部区 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Award className="w-4 h-4 text-amber-400" />
          <span className="text-sm font-semibold text-amber-400">英雄模式 / 声望挑战配置</span>
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
            <span>开启声望/英雄模式挑战</span>
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
        <div className="mt-3 pt-3 border-t border-[#243044] space-y-4">
          {/* 说明卡片 */}
          <div className="bg-[#0b1220] p-3 rounded-lg border border-[#243044] text-xs text-slate-300 flex items-start gap-2">
            <Info className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="text-amber-300 font-medium">
                声望挑战为 1-8 难度及以上解锁的【英雄模式】。
              </p>
              <p className="text-slate-400">
                脚本会在完成基础关卡选择后，自动点击右下角【英雄模式】入口，选中以下配置的目标声望与难度等级进行挑战。
              </p>
            </div>
          </div>

          {/* 6 个可选声望卡片 */}
          <div>
            <label className="text-xs font-medium text-[#8b9bb4] block mb-2">
              选择目标声望 (6 选 1):
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
              {REPUTATION_OPTIONS.map((rep) => {
                const isSelected = currentRepId === rep.id;
                const IconComp = rep.icon;

                return (
                  <button
                    key={rep.id}
                    type="button"
                    disabled={disabled}
                    onClick={() => onChange('reputation_type', rep.id)}
                    className={`flex items-start gap-3 p-3 rounded-xl border text-left transition-all ${
                      isSelected
                        ? 'bg-blue-600/15 border-blue-500 shadow-md shadow-blue-500/10'
                        : 'bg-[#0b1220] border-[#243044] hover:border-slate-500 opacity-80 hover:opacity-100'
                    } disabled:opacity-50`}
                  >
                    <div className={`p-2 rounded-lg border ${rep.color} shrink-0`}>
                      <IconComp className="w-5 h-5" />
                    </div>
                    <div className="space-y-0.5">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-bold text-white">{rep.id}. {rep.name}</span>
                        {isSelected && (
                          <span className="text-[10px] bg-blue-500 text-white font-semibold px-1.5 py-0.2 rounded">
                            已选
                          </span>
                        )}
                      </div>
                      <span className="text-[11px] text-slate-400 block">{rep.desc}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* 难度等级调节 (1 - 10 级) */}
          <div className="bg-[#0b1220] p-3.5 rounded-lg border border-[#243044] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
            <div>
              <span className="text-xs font-medium text-slate-200 block">挑战难度等级 (1 ~ 10 级)</span>
              <span className="text-[11px] text-[#8b9bb4]">当前设置：挑战难度 Level {currentLevel}</span>
            </div>

            <div className="flex items-center gap-2">
              {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((lvl) => (
                <button
                  key={lvl}
                  type="button"
                  disabled={disabled}
                  onClick={() => onChange('reputation_level', lvl)}
                  className={`w-7 h-7 rounded-lg text-xs font-bold transition-all border ${
                    currentLevel === lvl
                      ? 'bg-amber-500 text-black border-amber-400 shadow'
                      : 'bg-[#151c2c] border-[#243044] text-slate-300 hover:border-slate-400'
                  } disabled:opacity-50`}
                >
                  {lvl}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
