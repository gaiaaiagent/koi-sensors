#!/bin/bash

# Full Phase 2 Validation Suite Runner
# Runs all validation tests and generates comprehensive reports

set -e  # Exit on error

echo "================================================================================"
echo "  KOI KNOWLEDGE GRAPH - PHASE 2 VALIDATION SUITE"
echo "================================================================================"
echo ""
echo "This script will:"
echo "  1. Test KG extraction on real sensor data (17 documents)"
echo "  2. Run end-to-end integration tests"
echo "  3. Analyze cross-sensor extraction quality"
echo "  4. Validate provenance chains (SQL queries)"
echo "  5. Generate cost & performance metrics report"
echo ""
echo "Press Ctrl+C to cancel, or Enter to continue..."
read

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR/.."

# Activate virtual environment
if [ -d "../../../venv" ]; then
    echo "Activating virtual environment..."
    source ../../../venv/bin/activate
else
    echo "Warning: Virtual environment not found at ../../../venv"
fi

# Set environment variables
export POSTGRES_URL=${POSTGRES_URL:-"postgresql://postgres:postgres@localhost:5433/eliza"}
export PYTHONPATH="${SCRIPT_DIR}/..:${PYTHONPATH}"

echo ""
echo "================================================================================"
echo "  TEST 1: Historical Data Processing (Real Sensor Data)"
echo "================================================================================"
echo ""

python tests/test_phase2_validation.py

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Historical data processing test failed!"
    echo "   Check the errors above and fix before continuing."
    exit 1
fi

echo ""
echo "✅ Historical data processing test complete!"
echo ""
echo "Press Enter to continue to integration tests..."
read

echo ""
echo "================================================================================"
echo "  TEST 2: End-to-End Integration Tests"
echo "================================================================================"
echo ""

python tests/test_e2e_integration.py

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Integration tests failed!"
    echo "   Check the errors above and fix before continuing."
    exit 1
fi

echo ""
echo "✅ Integration tests complete!"
echo ""
echo "Press Enter to continue to cross-sensor analysis..."
read

echo ""
echo "================================================================================"
echo "  TEST 3: Cross-Sensor Validation & Quality Analysis"
echo "================================================================================"
echo ""

python tests/validate_cross_sensor.py

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Cross-sensor validation failed!"
    echo "   Check the errors above."
    exit 1
fi

echo ""
echo "✅ Cross-sensor validation complete!"
echo ""
echo "Press Enter to continue to provenance validation..."
read

echo ""
echo "================================================================================"
echo "  TEST 4: Provenance Chain Validation (SQL Queries)"
echo "================================================================================"
echo ""

echo "Running provenance validation queries..."

psql "$POSTGRES_URL" -f tests/validate_provenance.sql > tests/provenance_validation_results.txt 2>&1

if [ $? -eq 0 ]; then
    echo "✅ Provenance validation queries executed successfully!"
    echo ""
    echo "Summary of key metrics:"
    echo ""
    grep -A 20 "PROVENANCE VALIDATION SUMMARY" tests/provenance_validation_results.txt || echo "(Full results in tests/provenance_validation_results.txt)"
else
    echo "❌ Provenance validation queries failed!"
    echo "   Check tests/provenance_validation_results.txt for details"
fi

echo ""
echo "Press Enter to continue to final metrics report..."
read

echo ""
echo "================================================================================"
echo "  TEST 5: Cost & Performance Metrics Report"
echo "================================================================================"
echo ""

python tests/generate_metrics_report.py

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Metrics report generation failed!"
    exit 1
fi

echo ""
echo "✅ Metrics report generated!"
echo ""

echo ""
echo "================================================================================"
echo "  VALIDATION SUITE COMPLETE!"
echo "================================================================================"
echo ""
echo "📊 Results Summary:"
echo ""
echo "  Test Results:"
echo "    ✅ Historical data processing"
echo "    ✅ End-to-end integration"
echo "    ✅ Cross-sensor validation"
echo "    ✅ Provenance chain validation"
echo "    ✅ Metrics report generation"
echo ""
echo "  Output Files:"
echo "    - tests/phase2_validation_results.json      (Detailed test results)"
echo "    - tests/kg_metrics_report.json              (Cost & performance metrics)"
echo "    - tests/provenance_validation_results.txt   (SQL validation results)"
echo ""
echo "  Next Steps:"
echo "    1. Review the output files for any issues"
echo "    2. Check provenance coverage (should be 100%)"
echo "    3. Review cost projections"
echo "    4. Decide on Phase 3 priorities"
echo ""
echo "================================================================================"
