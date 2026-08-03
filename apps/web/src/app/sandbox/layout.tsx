import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Argonis — AML investigation sandbox",
  description:
    "Synthetic AML investigation reconstructions where every claim is traceable and screening gaps are declared.",
};

export default function SandboxLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
