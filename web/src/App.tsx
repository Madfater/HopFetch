import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { Tooltip } from 'radix-ui'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Outlet, Route, Routes } from 'react-router'
import { APP_NAME } from './app-name'
import { api } from './api/client'
import { NavBar } from './components/NavBar'
import { ToastProvider } from './components/Toasts'
import { useToast } from './components/toast-context'
import { connectEvents } from './lib/events'
import { errorText } from './lib/messages'
import { isActive, TASKS_KEY, type Finished } from './lib/tasks'
import { Home } from './routes/Home'
import { Settings } from './routes/Settings'
import { Tasks } from './routes/Tasks'

// - App shell: query cache, router, tooltips and toasts, then one event stream for the whole app.
// - The tab title shows `(n) APP_NAME` while n tasks are queued or downloading.
// - A task that completes or fails while the page is open raises a toast.

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Tooltip.Provider delayDuration={300}>
          <ToastProvider>
            <Routes>
              <Route element={<Layout />}>
                <Route index element={<Home />} />
                <Route path="tasks" element={<Tasks />} />
                <Route path="settings" element={<Settings />} />
                <Route path="*" element={<Home />} />
              </Route>
            </Routes>
          </ToastProvider>
        </Tooltip.Provider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

function Layout() {
  const { t } = useTranslation()
  const toast = useToast()
  const client = useQueryClient()
  const [connected, setConnected] = useState(true)
  const tasks = useQuery({ queryKey: TASKS_KEY, queryFn: ({ signal }) => api.tasks(signal) })

  const notify = useRef<(finished: Finished) => void>(() => {})
  useEffect(() => {
    notify.current = ({ task, outcome }) => {
      const name = task.file_name ?? t('tasks.unnamed')
      if (outcome === 'completed') toast(t('toast.completed', { name }), 'success')
      else toast(t('toast.failed', { name, reason: errorText(t, task.error) }), 'error')
    }
  }, [t, toast])

  useEffect(
    () => connectEvents(client, { onConnection: setConnected, onFinished: (finished) => notify.current(finished) }),
    [client],
  )

  const active = (tasks.data ?? []).filter(isActive).length
  useEffect(() => {
    document.title = active > 0 ? `(${active}) ${APP_NAME}` : APP_NAME
  }, [active])

  return (
    <>
      <NavBar connected={connected} />
      <Outlet />
    </>
  )
}
