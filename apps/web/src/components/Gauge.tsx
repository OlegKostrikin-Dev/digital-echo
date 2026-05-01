type Props = {
  /** Значение от 0 до 1 */
  value: number;
  /** Подпись под процентом */
  caption?: string;
  /** Размер в пикселях */
  size?: number;
};

/**
 * Круговая шкала (donut) для отображения индекса КС.
 * Цвет автоматически выбирается по диапазону:
 * - >= 0.7 — зелёный (высокий КС)
 * - 0.4..0.7 — янтарный (средний)
 * - < 0.4 — красный (низкий)
 */
export function Gauge({ value, caption, size = 180 }: Props) {
  const pct = Math.max(0, Math.min(1, value));
  const display = Math.round(pct * 100);

  const radius = 78;
  const stroke = 14;
  const cx = 100;
  const cy = 100;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - pct);

  let color = "#ef4444";
  let bgColor = "#fef2f2";
  if (pct >= 0.7) {
    color = "#10b981";
    bgColor = "#ecfdf5";
  } else if (pct >= 0.4) {
    color = "#f59e0b";
    bgColor = "#fffbeb";
  }

  return (
    <div
      className="relative flex items-center justify-center"
      style={{ width: size, height: size }}
    >
      <svg
        viewBox="0 0 200 200"
        width={size}
        height={size}
        className="overflow-visible"
      >
        <circle cx={cx} cy={cy} r={radius} fill={bgColor} />
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke="#e2e8f0"
          strokeWidth={stroke}
        />
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeDasharray={`${circumference} ${circumference}`}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform={`rotate(-90 ${cx} ${cy})`}
          style={{ transition: "stroke-dashoffset 600ms ease-out" }}
        />
        <text
          x={cx}
          y={cy + 6}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize="38"
          fontWeight="700"
          fill="#0f172a"
        >
          {display}%
        </text>
        {caption && (
          <text
            x={cx}
            y={cy + 36}
            textAnchor="middle"
            fontSize="11"
            fill="#64748b"
          >
            {caption}
          </text>
        )}
      </svg>
    </div>
  );
}
