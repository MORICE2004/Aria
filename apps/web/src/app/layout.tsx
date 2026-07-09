/**
 * Root layout — the persistent dashboard shell (sidebar + content).
 * Theme is dark-only by design: ARIA's visual language is a dark-tech
 * "ops room" aesthetic (see globals.css for the tokens).
 */
import type { Metadata, Viewport } from "next";
import { Geist } from "next/font/google";
import "./globals.css";
import { NotificationBell } from "@/components/notification-bell";
import { Sidebar } from "@/components/sidebar";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "ARIA — Personal AI Assistant",
  description: "Your personal AI operating system.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg" },
};

export const viewport: Viewport = {
  themeColor: "#05070d",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`dark ${geistSans.variable}`}>
      <body className="min-h-screen font-sans antialiased">
        <div className="flex min-h-screen">
          <Sidebar />
          <main className="min-w-0 flex-1 p-4 md:p-8">{children}</main>
        </div>
        <NotificationBell />
      </body>
    </html>
  );
}
