import React from 'react';
import { Sparkles, RefreshCw, XCircle } from 'lucide-react';
import { SkillOption } from '../types';

const SKILL_NAMES: Record<string, string> = {
  asj: '奥数箭',
  asjg: '奥数激光',
  assx: '奥数射线',
  bsxx: '冰霜新星',
  byj: '爆炎箭',
  dcw: '电磁网',
  dz: '地震',
  hbj: '寒冰箭',
  hq: '火球',
  jf: '飓风',
  jq: '剑气',
  ljf: '龙卷风',
  pg: '普攻',
  sdl: '闪电链',
  tl: '天雷',
  ys: '陨石',
};

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
    // 过滤重复和空串
    const filtered = updated.filter((s, idx, self) => s !== '' && self.indexOf(s) === idx);
    onChange(filtered);
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
    <div className="bg-[#151c2c] border border-[#243044] rounded-xl p-4 shadow-sm space-y-3">
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

      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
        {[0, 1, 2, 3].map((slotIdx) => {
          const val = currentSkills[slotIdx];
          const cnName = SKILL_NAMES[val] || '';

          return (
            <div key={slotIdx} className="space-y-1.5 bg-[#0b1220] p-2.5 rounded-lg border border-[#243044]">
              <label className="text-xs font-medium text-slate-300 flex items-center justify-between">
                <span>技能 Slot {slotIdx + 1}</span>
                {cnName && <span className="text-blue-400 font-normal">{cnName}</span>}
              </label>

              <select
                value={val}
                onChange={(e) => handleSelectChange(slotIdx, e.target.value)}
                disabled={disabled}
                className="w-full bg-[#151c2c] border border-[#243044] rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
              >
                <option value="">-- 未选择 (无) --</option>
                {availableSkills.map((sk) => {
                  const label = SKILL_NAMES[sk.code]
                    ? `${SKILL_NAMES[sk.code]} (${sk.code})`
                    : sk.code;
                  return (
                    <option key={sk.code} value={sk.code}>
                      {label}
                    </option>
                  );
                })}
              </select>
            </div>
          );
        })}
      </div>
    </div>
  );
};
