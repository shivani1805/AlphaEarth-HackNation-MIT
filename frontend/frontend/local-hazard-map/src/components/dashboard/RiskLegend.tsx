import { Card } from "@/components/ui/card";
import { Info } from "lucide-react";

interface RiskLegendProps {
  disasterType?: "flood" | "hurricane" | "wildfire";
  startDate?: Date;
  endDate?: Date;
  isAnalyzing?: boolean;
}

const RiskLegend = ({ disasterType, startDate, endDate, isAnalyzing }: RiskLegendProps) => {
  const riskLevels = [
    { label: "Low", color: "risk-low" },
    { label: "Medium", color: "risk-medium" },
    { label: "High", color: "risk-high" },
  ];

  // Hardcoded claim amount ranges based on hazard type
  const getClaimAmounts = () => {
    if (!disasterType || !startDate || !endDate || !isAnalyzing) {
      return null;
    }

    if (disasterType === "flood") {
      return {
        low: "$18,750 - $56,250",
        medium: "$56,250 - $150,000",
        high: "$150,000 - $300,000",
      };
    } else if (disasterType === "hurricane") {
      return {
        low: "$7,500 - $30,000",
        medium: "$30,000 - $93,750",
        high: "$93,750 - $225,000",
      };
    }
    return null;
  };

  const claimAmounts = getClaimAmounts();
  const showAmounts = claimAmounts !== null;

  return (
    <Card className="p-6 bg-card border-border">
      <div className="flex items-center gap-2 mb-4">
        <Info className="h-5 w-5 text-primary" />
        <h3 className="text-lg font-semibold">Risk Score Legend</h3>
      </div>

      <div className="space-y-3">
        {riskLevels.map((level, index) => (
          <div key={index} className="flex items-center gap-3">
            <div 
              className={`w-8 h-8 rounded bg-${level.color} border border-border`}
              style={{ backgroundColor: `hsl(var(--${level.color}))` }}
            />
            <div className="font-medium text-sm">{level.label}</div>
          </div>
        ))}
      </div>

      <div className="mt-6 pt-6 border-t border-border">
        <h4 className="font-medium text-sm mb-3">Claim Amount Scale</h4>
        <div className="space-y-2 text-sm">
          {showAmounts ? (
            <>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Low:</span>
                <span className="text-chart-1">{claimAmounts.low}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Medium:</span>
                <span className="text-chart-3">{claimAmounts.medium}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">High:</span>
                <span className="text-chart-5">{claimAmounts.high}</span>
              </div>
            </>
          ) : (
            <div className="flex justify-center py-2">
              <span className="text-muted-foreground">N/A</span>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
};

export default RiskLegend;
