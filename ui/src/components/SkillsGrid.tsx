import React from 'react';
import { Sparkles, RefreshCw, XCircle, Check } from 'lucide-react';
import { SkillOption } from '../types';

export const SKILL_NAMES: Record<string, string> = {
  pg: '普攻',
  asj: '奥术箭',
  byj: '爆炎箭',
  hbj: '寒冰箭',
  tl: '天雷',
  jq: '剑气',
  asjg: '奥术激光',
  assx: '奥术射线',
  bsxx: '冰霜新星',
  sdl: '闪电链',
  dz: '地震',
  ys: '陨石',
  dcw: '电磁网',
  ys: '陨石',
  jf: '飓风',
  hq: '火球',
};

const ALL_SKILL_CODES = [
  'pg', 'asj', 'byj', 'hbj', 'tl',
  'jq', 'asjg', 'assx', 'bsxx', 'sdl',
  'dz', 'ljf', 'dcw', 'ys', 'jf', 'hq'
];

interface SkillsGridProps {
  skills: string[];
  onChange: (skills: string[]) => void;
  availableSkills: SkillOption[];
  disabled?: boolean;
}

export const SkillsGrid: React.FC<SkillsGridProps> = ({
  skills,
  onChange,
  availableSkills,
  disabled = false,
}) => {
  const currentSkills = [
    skills[0] || '',
    skills[1] || '',
    skills[2] || '',
    skills[3] || '',
  ];

  const handleSelectChange = (index: number, val: string) => {
    if (disabled) return;
    const updated = [...currentSkills];
    updated[index] = val;
    const filtered = updated.filter((s, idx, self) => s !== '' && self.indexOf(s) === idx);
    onChange(filtered);
  };

  const toggleSkillCode = (code: string) => {
    if (disabled) return;
    if (skills.includes(code)) {
      onChange(skills.filter((s) => s !== code));
    } else {
      if (skills.length >= 4) {
        // 如果已满4个，替换最后一个或忽略
        const next = [...skills.slice(0, 3), code];
        onChange(next);
      } else {
        onChange([...skills, code]);
      }
    }
  };

  const defaultOfficial = () => {
    if (disabled) return;
    onChange(['asj', 'asjg', 'assx', 'jq']);
  };

  const clearAll = () => {
    if (disabled) return;
    onChange([]);
  };

  return (
    <div className="bg-[#151c2c] border border-[#243044] rounded-xl p-4 shadow-sm space-y-4">
      {/* 标题与控制按钮 */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 border-b border-[#243044] pb-2.5">
        <div className="flex items-center gap-2 text-sm font-semibold text-blue-400">
          <Sparkles className="w-4 h-4 text-amber-400" />
          <span>主要技能设置 (最多选择 4 个)</span>
          <span className="text-xs text-[#8b9bb4] font-normal">
            (当前已选 {skills.length} / 4 个)
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={defaultOfficial}
            disabled={disabled}
            className="px-2.5 py-1 bg-[#0b1220] border border-[#243044] text-xs text-blue-400 hover:text-blue-300 rounded-lg flex items-center gap-1 hover:border-blue-500 transition-all disabled:opacity-50"
          >
            <RefreshCw className="w-3 h-3" />
            <span>重置官方标准 4 技能</span>
          </button>

          <button
            type="button"
            onClick={clearAll}
            disabled={disabled}
            className="px-2.5 py-1 bg-[#0b1220] border border-[#243044] text-xs text-slate-300 hover:text-white rounded-lg flex items-center gap-1 hover:border-red-500 transition-all disabled:opacity-50"
          >
            <XCircle className="w-3 h-3 text-red-400" />
            <span>清空</span>
          </button>
        </div>
      </div>

      {/* 4 个 Slot 选择槽 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
        {[0, 1, 2, 3].map((slotIdx) => {
          const val = currentSkills[slotIdx];
          const cnName = SKILL_NAMES[val] || '';

          return (
            <div key={slotIdx} className="space-y-2 bg-[#0b1220] p-3 rounded-lg border border-[#243044]">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-300">技能 Slot {slotIdx + 1}</span>
                {cnName && (
                  <span className="text-xs text-blue-400 font-medium px-1.5 py-0.5 bg-blue-500/10 rounded border border-blue-500/20">
                    {cnName}
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                {val ? (
                  <img
                    src={`/assets/Images/skills/${val}.png`}
                    alt={cnName}
                    className="w-9 h-9 rounded-lg border border-blue-500/40 object-cover bg-black/40 shrink-0"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = 'none';
                    }}
                  />
                ) : (
                  <div className="w-9 h-9 rounded-lg border border-dashed border-[#243044] flex items-center justify-center text-xs text-slate-600 shrink-0">
                    空
                  </div>
                )}

                <select
                  value={val}
                  onChange={(e) => handleSelectChange(slotIdx, e.target.value)}
                  disabled={disabled}
                  className="w-full bg-[#151c2c] border border-[#243044] rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
                >
                  <option value="">-- 未选择 (无) --</option>
                  {ALL_SKILL_CODES.map((code) => {
                    const label = SKILL_NAMES[code] ? `${SKILL_NAMES[code]} (${code})` : code;
                    return (
                      <option key={code} value={code}>
                        {label}
                      </option>
                    );
                  })}
                </select>
              </div>
            </div>
          );
        })}
      </div>

      {/* 技能图鉴可视化选择画廊 */}
      <div className="pt-2">
        <label className="text-xs font-medium text-[#8b9bb4] block mb-2">
          技能画廊 (点击图标快速选择/取消):
        </label>
        <div className="grid grid-cols-4 sm:grid-cols-8 md:grid-cols-8 gap-2 bg-[#0b1220] p-3 rounded-lg border border-[#243044]">
          {ALL_SKILL_CODES.map((code) => {
            const isSelected = skills.includes(code);
            const cnName = SKILL_NAMES[code] || code;

            return (
              <button
                key={code}
                type="button"
                disabled={disabled}
                onClick={() => toggleSkillCode(code)}
                className={`relative flex flex-col items-center p-1.5 rounded-lg border transition-all ${
                  isSelected
                    ? 'bg-blue-600/20 border-blue-500 shadow-md shadow-blue-500/10'
                    : 'bg-[#151c2c] border-[#243044] hover:border-slate-500 opacity-80 hover:opacity-100'
                } disabled:opacity-50`}
              >
                <div className="relative w-10 h-10 mb-1">
                  <img
                    src={`/assets/Images/skills/${code}.png`}
                    alt={cnName}
                    className="w-full h-full rounded border border-slate-700/50 object-cover"
                  />
                  {isSelected && (
                    <div className="absolute -top-1 -right-1 bg-blue-500 text-white rounded-full p-0.5 shadow">
                      <Check className="w-3 h-3" />
                    </div>
                  )}
                </div>
                <span className={`text-[11px] font-medium truncate w-full text-center ${isSelected ? 'text-blue-300' : 'text-slate-300'}`}>
                  {cnName}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};
