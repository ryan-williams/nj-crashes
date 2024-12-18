import { NextApiRequest, NextApiResponse } from "next";
import { CrashPageOpts } from "@/src/query";
import { DefaultPageSize } from "@/src/pagination";
import { Crashes } from "@/server/njsp/sql";
import { getUrls } from "@/src/urls";
import { CrashPage } from "@/src/njsp/crash";

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse<CrashPage>
) {
  console.log("/api/njsp/crashes req.query:", req.query)
  const { p: page = 0, pp: perPage = DefaultPageSize, cc = null, mc = null } = req.query as CrashPageOpts
  const urls = getUrls({ local: true })
  const crashDb = new Crashes(urls.njsp.crashes)
  const crashPage = await crashDb.crashPage({ cc, mc, page, perPage, })
  res.status(200).json(crashPage)
}
