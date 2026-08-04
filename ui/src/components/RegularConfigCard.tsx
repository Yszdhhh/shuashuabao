import React from 'react';
import { Settings, Target, Flame, Crown, Clock, ToggleLeft } from 'lucide-react';
import { AppSettings, BossesResponse } from '../types';

interface RegularConfigCardProps {
  settings: AppSettings;
  onChange: (key: keyof AppSettings, value: any) => void;
  bosses: BossesResponse;
  disabled?: boolean;
}

export const RegularConfigCard: React.FC<RegularConfigCardProps> = ({
  settings,
  onChange,
  bosses,
  disabled = false,
}) => {
  return (
    <div className="bg-[#151c2c] border border-[#243044] rounded-xl p-4 shadow-sm">
      <div className="flex items-center justify-between border-b border-[#243044] pb-2.5 mb-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-blue-400">
          <Settings className="w-4 h-4" />
          <span>常规运行配置 (P0)</span>
        </div>
        <span className="text-xs text-[#8b9bb4]">最常用的核心刷图参数</span>
      </div>

      <div className="space-y-4">
        {/* 关卡与 Boss 下拉 */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* 目标关卡起止 */}
          <div className="bg-[#0b1220] p-3 rounded-lg border border-[#243044]">
            <label className="text-xs font-medium text-[#8b9bb4] flex items-center gap-1.5 mb-2">
              <Target className="w-3.5 h-3.5 text-blue-400" />
              <span>目标关卡范围 (stage1 — stage2)</span>
            </label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={1}
                max={50}
                value={settings.stage1}
                disabled={disabled}
                onChange={(e) => onChange('stage1', parseInt(e.target.value) || 1)}
                className="w-20 bg-[#151c2c] border border-[#243044] rounded px-3 py-1.5 text-sm font-semibold text-white focus:outline-none focus:border-blue-500 text-center"
              />
              <span className="text-slate-400 font-bold">—</span>
              <input
                type="number"
                min={1}
                max={50}
                value={settings.stage2}
                disabled={disabled}
                onChange={(e) => onChange('stage2', parseInt(e.target.value) || 10)}
                className="w-20 bg-[#151c2c] border border-[#243044] rounded px-3 py-1.5 text-sm font-semibold text-white focus:outline-none focus:border-blue-500 text-center"
              />
              <span className="text-xs text-[#8b9bb4] ml-2">关 (推荐 1 — 10)</span>
            </div>
          </div>

          {/* 龙珠数 / 超时 / 发育时间 */}
          <div className="bg-[#0b1220] p-3 rounded-lg border border-[#243044]">
            <label className="text-xs font-medium text-[#8b9bb4] flex items-center gap-1.5 mb-2">
              <Flame className="w-3.5 h-3.5 text-amber-400" />
              <span>龙珠与发育计时</span>
            </label>
            <div className="grid grid-cols-3 gap-2">
              <div>
                <span className="text-[11px] text-[#8b9bb4] block mb-1">龙珠数</span>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={settings.dragon_ball_count}
                  disabled={disabled}
                  onChange={(e) => onChange('dragon_ball_count', parseInt(e.target.value) || 7)}
                  className="w-full bg-[#151c2c] border border-[#243044] rounded px-2 py-1 text-xs text-white text-center font-medium focus:border-blue-500"
                />
              </div>

              <div>
                <span className="text-[11px] text-[#8b9bb4] block mb-1">等待UI(秒)</span>
                <input
                  type="number"
                  min={10}
                  max={600}
                  value={settings.query_timeout}
                  disabled={disabled}
                  onChange={(e) => onChange('query_timeout', parseInt(e.target.value) || 120)}
                  className="w-full bg-[#151c2c] border border-[#243044] rounded px-2 py-1 text-xs text-white text-center font-medium focus:border-blue-500"
                />
              </div>

              <div>
                <span className="text-[11px] text-[#8b9bb4] block mb-1">发育时间(0=快刷)</span>
                <input
                  type="number"
                  min={0}
                  max={3000}
                  value={settings.develop_time}
                  disabled={disabled}
                  onChange={(e) => onChange('develop_time', parseInt(e.target.value) || 0)}
                  className="w-full bg-[#151c2c] border border-[#243044] rounded px-2 py-1 text-xs text-white text-center font-medium focus:border-blue-500"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Boss 下拉选项 */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* 主线 Boss */}
          <div className="bg-[#0b1220] p-3 rounded-lg border border-[#243044]">
            <label className="text-xs font-medium text-[#8b9bb4] flex items-center gap-1.5 mb-2">
              <Crown className="w-3.5 h-3.5 text-purple-400" />
              <span>主线 / 地图 Boss (sgzx_boss)</span>
            </label>
            <select
              value={settings.sgzx_boss}
              disabled={disabled}
              onChange={(e) => onChange('sgzx_boss', e.target.value)}
              className="w-full bg-[#151c2c] border border-[#243044] rounded px-3 py-1.5 text-xs text-slate-100 font-medium focus:border-blue-500 focus:outline-none"
            >
              {bosses.main.length === 0 ? (
                <option value="">未扫描到主线 Boss</option>
              ) : (
                bosses.main.map((b) => (
                  <option key={b.name} value={b.name}>
                    {b.name}
                  </option>
                ))
              )}
            </select>
          </div>

          {/* 传家宝 Boss */}
          <div className="bg-[#0b1220] p-3 rounded-lg border border-[#243044]">
            <label className="text-xs font-medium text-[#8b9bb4] flex items-center gap-1.5 mb-2">
              <Crown className="w-3.5 h-3.5 text-emerald-400" />
              <span>传家宝 Boss (cjb_boss)</span>
            </label>
            <select
              value={settings.cjb_boss}
              disabled={disabled}
              onChange={(e) => onChange('cjb_boss', e.target.value)}
              className="w-full bg-[#151c2c] border border-[#243044] rounded px-3 py-1.5 text-xs text-slate-100 font-medium focus:border-blue-500 focus:outline-none"
            >
              {bosses.cjb.length === 0 ? (
                <option value="">未扫描到传家宝 Boss</option>
              ) : (
                bosses.cjb.map((b) => (
                  <option key={b.name} value={b.name}>
                    {b.name}
                  </option>
                ))
              )}
            </select>
          </div>
        </div>

        {/* 自动化开关组 */}
        <div className="bg-[#0b1220] p-3 rounded-lg border border-[#243044]">
          <label className="text-xs font-medium text-[#8b9bb4] flex items-center gap-1.5 mb-2.5">
            <ToggleLeft className="w-3.5 h-3.5 text-blue-400" />
            <span>自动选卡与行为开关</span>
          </label>

          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-2">
            {[
              { key: 'auto_card', label: '自动卡组' },
              { key: 'auto_weapon', label: '自动武器' },
              { key: 'damage_increase_card', label: '奥数增伤' },
              { key: 'develop_priority', label: '发育优先' },
              { key: 'auto_secret_realm', label: '自动秘境' },
            ].map(({ key, label }) => {
              const val = settings[key as keyof AppSettings] as boolean;
              return (
                <button
                  key={key}
                  type="button"
                  disabled={disabled}
                  onClick={() => onChange(key as keyof AppSettings, !val)}
                  className={`flex items-center justify-between px-3 py-2 rounded-lg border text-xs font-medium transition-all ${
                    val
                      ? 'bg-blue-600/20 border-blue-500/50 text-blue-300'
                      : 'bg-[#151c2c] border-[#243044] text-[#8b9bb4] hover:text-slate-200'
                  }`}
                >
                  <span>{label}</span>
                  <span
                    className={`w-3.5 h-3.5 rounded-full flex items-center justify-center text-[9px] font-bold ${
                      val ? 'bg-blue-500 text-white' : 'bg-slate-700 text-slate-400'
                    }`}
                  >
                    {val ? '✓' : ''}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
