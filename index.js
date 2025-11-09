const express = require("express");
const cors = require("cors");
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const csv = require("csv-parser");

const app = express();
const PORT = 5001;

app.use(cors());
app.use(express.json());

app.post("/api/county-risk", async (req, res) => {
  try {
    const data = req.body;
    console.log("Received county risk data:", data);

    const jsonPath = path.join(__dirname, "countyRiskData.json");
    fs.writeFileSync(jsonPath, JSON.stringify(data, null, 2));
    const pythonProcess = spawn("python3", [
      path.join(__dirname, "points_to_hazard_csv.py"),
      jsonPath
    ]);

    pythonProcess.stdout.on("data", (data) => {
      console.log(`Python stdout: ${data}`);
    });

    pythonProcess.stderr.on("data", (data) => {
      console.error(`Python stderr: ${data}`);
    });

    pythonProcess.on("close", (code) => {
      if (code === 0) {
        const csvPath = path.join(__dirname, "results/csv/point_daily_metrics.csv");
        const results = [];

        fs.createReadStream(csvPath)
          .pipe(csv())
          .on("data", (row) => {
            results.push({
              county: row.name,
              flood_category: row.flood_category,
              hurricane_category: row.hurricane_category,
              wildfire_category:row.wildfire_category
            });
          })
          .on("end", () => {
            res.status(200).json(results);
          })
          .on("error", (err) => {
            console.error("Error reading CSV:", err);
            res.status(500).json({ message: "Failed to read CSV" });
          });

      } else {
        res.status(500).json({ message: `Python script exited with code ${code}` });
      }
    });
  } catch (error) {
    console.error(error);
    res.status(500).json({ message: "Server error" });
  }
});

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});
