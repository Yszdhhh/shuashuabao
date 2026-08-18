import React, { useState, useEffect } from 'react';
import { Shield, Layers, XCircle } from 'lucide-react';
import { AppSettings, CardOption } from '../types';

const FETTER_NAMES: Record<string, string> = {
  baoji: '暴击',
  chengzhang: '成长',
  dapao: '大炮',
  dasheng: '大圣',
  dashengcanqu: '大圣残躯',
  dashengtaozhuang: '大圣套装',
  fs: '法术',
  genji: '根基',
  gongshen: '弓神',
  gunfa: '棍法',
  gushou: '鼓手',
  jj: '箭术',
  liemoren: '猎魔人',
  liliang: '力量',
  mfs: '魔法师',
  mingjie: '敏捷',
  qiji: '奇迹',
  shenfa: '身法',
  shengming: '生命',
  shougezhe: '收割者',
  shufa: '术法',
  tanlan: '贪婪',
  tishu: '体术',
  tuluzhe: '屠戮者',
  tz: '套装',
  xianzhen: '陷阵',
  xuemo: '血魔',
  xueshi: '血誓',
  yanmiezhe: '湮灭者',
  yemanren: '野蛮人',
  yihuo: '翼火',
  zhanshen: '战神',
  zhanshu: '战术',
  zhili: '智力',
  zhiming: '致命',
  zhufu: '祝福',
};

interface FettersCardProps {
  settings: AppSettings;
  onChange: (key: keyof AppSettings, value: any) => void;
  disabled?: boolean;
}

export const FettersCard: React.FC<FettersCardProps> = ({
  settings,
  onChange,
  disabled = false,
}) => {
  const [cardsOptions, setCardsOptions] = useState<CardOption[]>([]);

  useEffect(() => {
    fetch('/api/options/cards')
      .then((res) => res.json())
      .then((data) => setCardsOptions(data))
      .catch(() => {});
  }, []);

  const cards = settings.cards || [];
  const currentCards = [
    cards[0] || '',
    cards[1] || '',
    cards[2] || '',
    cards[3] || '',
  ];

  const handleSelectChange = (index: number, val: string) => {
    if (disabled) return;
    const updated = [...currentCards];
    updated[index] = val;
    const filtered = updated.filter((s, idx, self) => s !== '' && self.indexOf(s) === idx);
    onChange('cards', filtered);
  };

  const clearAll = () => {
    if (disabled) return;
    onChange('cards', []);
  };

  return (
    <div className="bg-[#151c2c] border border-[#243044] rounded-xl p-4 shadow-sm space-y-3">
      <div className="flex items-center justify-between border-b border-[#243044] pb-2.5">
        <div className="flex items-center gap-2 text-sm font-semibold text-blue-400">
          <Layers className="w-4 h-4 text-purple-400" />
          <span>主要羁绊与卡牌偏好 (Cards 下拉设置)</span>
          <span className="text-xs text-[#8b9bb4] font-normal">
            (已设置 {cards.length} / 4 项)
          </span>
        </div>

        <button
          type="button"
          onClick={clearAll}
          disabled={disabled}
          className="px-2.5 py-1 bg-[#0b1220] border border-[#243044] text-xs text-slate-300 hover:text-white rounded-lg flex items-center gap-1 hover:border-red-500 transition-all disabled:opacity-50"
        >
          <XCircle className="w-3 h-3 text-red-400" />
          <span>清空羁绊</span>
        </button>
      </div>

      {/* 4 个羁绊下拉 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
        {[0, 1, 2, 3].map((slotIdx) => {
          const val = currentCards[slotIdx];
          const cnName = FETTER_NAMES[val] || val || '';

          return (
            <div key={slotIdx} className="space-y-1.5 bg-[#0b1220] p-2.5 rounded-lg border border-[#243044]">
              <label className="text-xs font-medium text-slate-300 flex items-center justify-between">
                <span>羁绊 Slot {slotIdx + 1}</span>
                {cnName && <span className="text-purple-400 font-normal">{cnName}</span>}
              </label>

              <select
                value={val}
                onChange={(e) => handleSelectChange(slotIdx, e.target.value)}
                disabled={disabled}
                className="w-full bg-[#151c2c] border border-[#243044] rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
              >
                <option value="">-- 未选择 (无) --</option>
                {cardsOptions.map((c) => {
                  const label = FETTER_NAMES[c.name]
                    ? `${FETTER_NAMES[c.name]} (${c.name})`
                    : c.name;
                  return (
                    <option key={c.name} value={c.name}>
                      {label}
                    </option>
                  );
                })}
              </select>
            </div>
          );
        })}
      </div>

      {/* 辅助开关 */}
      <div className="pt-2 border-t border-[#243044]/60 grid grid-cols-2 sm:grid-cols-4 gap-2">
        <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
          <input
            type="checkbox"
            checked={settings.auto_card}
            onChange={(e) => onChange('auto_card', e.target.checked)}
            disabled={disabled}
            className="rounded bg-[#0a101c] border-[#243044] text-blue-600 focus:ring-0"
          />
          <span>自动卡组 (AutoCard)</span>
        </label>

        <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
          <input
            type="checkbox"
            checked={settings.auto_weapon}
            onChange={(e) => onChange('auto_weapon', e.target.checked)}
            disabled={disabled}
            className="rounded bg-[#0a101c] border-[#243044] text-blue-600 focus:ring-0"
          />
          <span>自动武器 (AutoWeapon)</span>
        </label>

        <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
          <input
            type="checkbox"
            checked={settings.damage_increase_card}
            onChange={(e) => onChange('damage_increase_card', e.target.checked)}
            disabled={disabled}
            className="rounded bg-[#0a101c] border-[#243044] text-blue-600 focus:ring-0"
          />
          <span>奥术增伤 (DamageIncrease)</span>
        </label>
        <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
          <input
            type="checkbox"
            checked={settings.develop_priority}
            onChange={(e) => onChange('develop_priority', e.target.checked)}
            disabled={disabled}
            className="rounded bg-[#0a101c] border-[#243044] text-blue-600 focus:ring-0"
          />
          <span>发育优先 (DevelopPriority)</span>
        </label>
      </div>
    </div>
  );
};
