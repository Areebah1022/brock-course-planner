"""A tiny, invented calendar page that mimics the structure of Brock's real one."""

FIXTURE_HTML = """
<html><head><title>2099-2100 Undergraduate Calendar - Testing</title></head><body>
<p class="calccode"><a name="TEST_1P01">TEST 1P01</a></p>
<p class="calcname">Intro Widgets</p>
<p class="calnormal">Learn about widgets.</p>
<p class="calitalic">Lectures, 3 hours per week.</p>
<p class="courseheading">INTERMEDIATE COURSES</p>

<p class="calccode"><a name="TEST_2P01">#TEST 2P01</a></p>
<p class="calcname">Advanced Widgets</p>
<p class="calnormal">(also offered as <a href="x.html">ALSO 2P01</a>)</p>
<p class="calnormal">Build bigger widgets.</p>
<p class="calitalic">Lectures, 3 hours per week; lab, 2 hours per week.</p>
<p class="calnormal">Restriction: open to TEST (single or combined) majors.</p>
<p class="calnormal">Prerequisite(s): <a href="x.html">TEST 1P01</a> (minimum 60 percent), <a href="x.html">MATH 1P66</a> and <a href="x.html">1P67</a>.</p>
<p class="calnormal">Note: offered in the fall.</p>
<p class="calnormal">Completion of this course will replace previous assigned grade and credit obtained in TEST 2P90 and 3P05.</p>

<p class="calccode"><a name="TEST_3P01">TEST 3P01</a></p>
<p class="calcname">Widget Algorithms(also offered as ALSO 3P01)</p>
<p class="calnormal">Sort widgets.</p>
<p class="calnormal">Prerequisite(s): TEST 1P01 (minimum 60 percent) and 1P02 (minimum 60 percent) or TEST 2P01 (minimum 70 percent).</p>

<p class="calccode"><a name="TEST_3P02">TEST 3P02</a></p>
<p class="calcname">Widget Choices</p>
<p class="calnormal">Pick widgets.</p>
<p class="calnormal">Prerequisite(s): one of TEST 1P01, TEST 2P01, MATH 2P40.</p>

<p class="calccode"><a name="TEST_3P03">TEST 3P03</a></p>
<p class="calcname">Widget Seminar</p>
<p class="calnormal">Talk about widgets.</p>
<p class="calnormal">Prerequisite(s): three and one-half TEST credits and permission of the instructor.</p>

<p class="calccode"><a name="TEST_3P04">TEST 3P04</a></p>
<p class="calcname">Widget Survey</p>
<p class="calnormal">Survey widgets.</p>
<p class="calnormal">Prerequisite(s): two credits from TEST (minimum 60 percent), MATH (minimum 60 percent), STAT (minimum 60 percent).</p>

<p class="calccode"><a name="TEST_3P05">TEST 3P05</a></p>
<p class="calcname">Widget Entry</p>
<p class="calnormal">Enter widgets.</p>
<p class="calnormal">Prerequisite(s): TEST 1P01 or 4U Mathematics credit.</p>

<p class="calccode"><a name="TEST_3P06">TEST 3P06</a></p>
<p class="calcname">Widget Variants</p>
<p class="calnormal">Vary widgets.</p>
<p class="calnormal">Prerequisite(s): TEST 1P01 for TEST majors; TEST 1P01 and MATH 1P66 for GAME majors.</p>

<p class="calccode"><a name="TEST_4P01">TEST 4P01</a></p>
<p class="calcname">Widget Topics</p>
<p class="calnormal">Mislabelled widgets.</p>
<p class="calnormal">Restriction: TEST 3P01 (minimum 70 percent).</p>

<p class="calccode"><a name="TEST_4P02">TEST 4P02</a></p>
<p class="calcname">Widget Placement</p>
<p class="calnormal">Work with widgets.</p>
<p class="calnormal">Prerequisite(s): SCIE 0N90.</p>
<p class="calnormal">Corequisite(s): TEST 0N01.</p>
<p class="calnormal">Last updated: January 2, 2099</p>
</body></html>
"""
