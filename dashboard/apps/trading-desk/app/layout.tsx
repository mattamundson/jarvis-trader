import { Inter } from 'next/font/google'
import './globals.css'
import { ToastProvider } from '@/lib/toast-context'

const inter = Inter({ subsets: ['latin'] })

export const metadata = {
  title: 'JARVIS Trading Desk',
  description: 'Live trading execution and monitoring',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  )
}
