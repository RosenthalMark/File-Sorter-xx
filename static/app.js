const dropZone = document.getElementById("dropZone");
const fileInput = document.getElementById("fileInput");
const log = document.getElementById("log");
const barFill = document.getElementById("barFill");
const meta = document.getElementById("meta");

const sourcePath = document.getElementById("sourcePath");
const outputPath = document.getElementById("outputPath");

const chooseSourceBtn = document.getElementById("chooseSourceBtn");
const chooseOutputBtn = document.getElementById("chooseOutputBtn");
const openOutputBtn = document.getElementById("openOutputBtn");
const processBtn = document.getElementById("processBtn");

function logLine(s){
  log.textContent += s + "\n";
  log.scrollTop = log.scrollHeight;
}

function setProgress(pct, label){
  barFill.style.width = `${pct}%`;
  meta.textContent = label || "";
}

async function refreshStats(){
  try{
    const r = await fetch("/api/stats");
    const j = await r.json();
    if(j.ok){
      sourcePath.textContent = `Source: ${j.source_dir}`;
      outputPath.textContent = `Output: ${j.output_dir}`;
      const n = j.next_id || {};
      logLine(`Indexed: ${j.total_indexed}`);
      logLine(`Next IDs: PIC=${n.PIC ?? "?"} VID=${n.VID ?? "?"} GIF=${n.GIF ?? "?"}`);
    }
  }catch(e){}
}

async function chooseSource(){
  const r = await fetch("/api/choose_source");
  const j = await r.json();
  if(j.ok){
    logLine("");
    logLine(`Source set to: ${j.source_dir}`);
    await refreshStats();
  }else{
    logLine("Choose source cancelled or failed.");
  }
}

async function chooseOutput(){
  const r = await fetch("/api/choose_output");
  const j = await r.json();
  if(j.ok){
    logLine("");
    logLine(`Output set to: ${j.output_dir}`);
    await refreshStats();
  }else{
    logLine("Choose output cancelled or failed.");
  }
}

async function openOutput(){
  const r = await fetch("/api/open_output");
  const j = await r.json();
  if(!j.ok){
    logLine("ERROR: Could not open output folder");
    if(j.error) logLine(j.error);
  }
}

async function processSource(){
  logLine("");
  logLine("Starting scan (copy mode)...");
  setProgress(2, "Starting...");

  const r = await fetch("/api/process_folder", { method: "POST" });
  const j = await r.json();
  if(!j.ok){
    logLine("ERROR: Could not start scan job");
    setProgress(0, "");
    return;
  }

  await pollJob(j.job_id);
}

async function pollJob(jobId){
  while(true){
    const r = await fetch(`/api/job/${jobId}`);
    const j = await r.json();
    if(!j.ok){
      logLine("ERROR: Job status failed");
      setProgress(0, "");
      return;
    }

    const job = j.job;
    const total = job.total || 0;
    const cur = job.current || 0;

    let pct = 0;
    if(total > 0) pct = Math.min(100, Math.round((cur / total) * 100));
    setProgress(pct, `Processing ${cur}/${total}`);

    if(job.done){
      const c = job.counts || {};
      logLine("");
      logLine(`Done. processed=${c.processed || 0} dupes=${c.dupes || 0} skipped=${c.skipped || 0}`);
      if(job.last_error){
        logLine(`Last error: ${job.last_error}`);
      }
      await refreshStats();
      setTimeout(() => setProgress(0, ""), 900);
      return;
    }

    await new Promise(res => setTimeout(res, 500));
  }
}

function uploadFiles(files){
  if(!files || files.length === 0) return;

  logLine("");
  logLine(`Uploading ${files.length} file(s) to Output...`);
  setProgress(0, "Uploading...");

  const form = new FormData();
  for(const f of files){
    form.append("files", f, f.name);
  }

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/upload");

  xhr.upload.onprogress = (evt) => {
    if(evt.lengthComputable){
      const pct = Math.round((evt.loaded / evt.total) * 100);
      setProgress(pct, `Uploading... ${pct}%`);
    }else{
      setProgress(30, "Uploading...");
    }
  };

  xhr.onerror = () => {
    setProgress(0, "Upload failed");
    logLine("ERROR: Upload failed");
  };

  xhr.onload = () => {
    if(xhr.status !== 200){
      setProgress(0, `Error ${xhr.status}`);
      logLine(`ERROR: Server returned ${xhr.status}`);
      logLine(xhr.responseText);
      return;
    }

    const j = JSON.parse(xhr.responseText);
    if(!j.ok){
      logLine("ERROR: " + (j.error || "unknown"));
      setProgress(0, "");
      return;
    }

    const c = j.counts;
    logLine(`Done. processed=${c.processed} dupes=${c.dupes} skipped=${c.skipped}`);
    logLine("----------");

    for(const r of j.results){
      if(r.status === "processed"){
        logLine(`OK   ${r.file}  ->  ${r.copied_to}  (key=${r.key})`);
      }else if(r.status === "dupe"){
        logLine(`DUPE ${r.file}  ->  ${r.copied_to}  (matches=${r.matches_key || "?"})`);
      }else{
        logLine(`SKIP ${r.file}  (${r.reason})`);
      }
    }

    refreshStats();
    setTimeout(() => setProgress(0, ""), 900);
  };

  xhr.send(form);
}

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("dragover");
});

dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("dragover");
  uploadFiles(e.dataTransfer.files);
});

fileInput.addEventListener("change", () => {
  uploadFiles(fileInput.files);
  fileInput.value = "";
});

chooseSourceBtn.addEventListener("click", chooseSource);
chooseOutputBtn.addEventListener("click", chooseOutput);
openOutputBtn.addEventListener("click", openOutput);
processBtn.addEventListener("click", processSource);

refreshStats();