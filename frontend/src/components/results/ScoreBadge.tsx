'use client';

import { getScoreColor, getScoreLabel } from '@/lib/utils';

interface ScoreBadgeProps {
  score: number;
  size?: 'sm' | 'md' | 'lg';
}

export default function ScoreBadge({ score, size = 'md' }: ScoreBadgeProps) {
  const color = getScoreColor(score);
  const label = getScoreLabel(score);

  const dims = { sm: 44, md: 56, lg: 68 };
  const dim = dims[size];
  const radius = (dim - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const strokeDash = (score / 100) * circumference;
  const fontSize = { sm: 10, md: 13, lg: 16 };
  const labelSize = { sm: 7, md: 8, lg: 9 };

  return (
    <div className="flex flex-col items-center gap-1">
      <svg
        width={dim}
        height={dim}
        viewBox={`0 0 ${dim} ${dim}`}
        className="rotate-[-90deg]"
        aria-label={`Score: ${score} — ${label}`}
      >
        {/* Track */}
        <circle
          cx={dim / 2}
          cy={dim / 2}
          r={radius}
          fill="none"
          stroke="#334155"
          strokeWidth={4}
        />
        {/* Progress */}
        <circle
          cx={dim / 2}
          cy={dim / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={4}
          strokeLinecap="round"
          strokeDasharray={`${strokeDash} ${circumference}`}
          style={{ transition: 'stroke-dasharray 0.6s ease' }}
        />
        {/* Score number (counter-rotated) */}
        <text
          x={dim / 2}
          y={dim / 2}
          textAnchor="middle"
          dominantBaseline="central"
          fill={color}
          fontSize={fontSize[size]}
          fontWeight="700"
          style={{ transform: `rotate(90deg)`, transformOrigin: `${dim / 2}px ${dim / 2}px` }}
        >
          {score}
        </text>
      </svg>
      <span
        className="font-medium tracking-wide uppercase"
        style={{ color, fontSize: labelSize[size] }}
      >
        {label}
      </span>
    </div>
  );
}
