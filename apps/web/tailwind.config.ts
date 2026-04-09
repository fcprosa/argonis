import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      colors: {
        // Design system tokens
        surface: {
          base: "#0A0A0A",
          1: "#111111",
          2: "#161616",
          3: "#1A1A1A",
        },
        border: {
          DEFAULT: "#1F1F1F",
          muted: "#161616",
          strong: "#2D2D2D",
        },
        text: {
          DEFAULT: "#FFFFFF",
          muted: "#6B7280",
          faint: "#3F3F3F",
        },
        accent: {
          DEFAULT: "#E8FF4D",
          hover: "#D4EB3A",
          dim: "#B8CC2E",
          subtle: "#1E2000",
        },
        danger: {
          DEFAULT: "#EF4444",
          subtle: "#2D0F0F",
        },
        success: {
          DEFAULT: "#22C55E",
          subtle: "#0D2416",
        },
        warn: {
          DEFAULT: "#F59E0B",
          subtle: "#2A1E06",
        },
        // Legacy compat
        sidebar: "#111111",
      },
    },
  },
  plugins: [],
};

export default config;
