import type { Metadata } from "next";

import { MenuCsr } from "@/components/MenuCsr";

export const metadata: Metadata = {
  title: "Меню (CSR)",
  description: "Демо клиентского рендеринга для сравнения с SSR.",
  robots: { index: false, follow: false },
};

export default function MenuCsrPage() {
  return <MenuCsr />;
}
