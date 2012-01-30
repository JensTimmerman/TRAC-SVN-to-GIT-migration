<?php

/**
 * This script converts the commit references from SVN IDs to GIT IDs, i.e. changing in all tickets
 * [1234] to [a42v2e3] or whatever the corresponding GIT hash is
 *
 * It needs a SVN ID -> GIT ID lookup table file called lookupTable.txt to match IDs.
 *
 * Execute it with php.exe convertTracTickets.php
 *
 * Needs the sqlite3 extension enabled to access the TRAC database.
 **/
error_reporting(E_ALL);

/* CONFIGURATION */

// String to open DB connection, in a format PDO accepts
//f.ex
// "pgsql:dbname=pdo;host=localhost"
// "sqlite:/path/to/database.sdb"
// "mysql:host=$hostname;dbname=mysql"
$DBString = "sqlite:/home/jens/tractest/db/trac.db";
//db username and password, leave blank for sqlite
$DBUser = "";
$DBPasswd = "";



// Path to lookup table (SVN revision number to GIT revion hash)
$pathLookupTable = "lookupTable.txt";

// Number of characters for the changeset hash. This has to be 4 <= nr <= 40
$nrHashCharacters = 40;

/* END CONFIGURATION */

/**
 * Converts a text with references to an SVN revision [1234] into the corresponding GIT revision
 *
 * @param text Text to convert
 * @param lookupTable Conversion table from SVN ID to Git ID
 * @returns True if conversions have been made
 */
function convertSVNIDToGitID(&$text, $lookupTable, $nrHashCharacters)
{		
	// Extract references to SVN revisions [####]
	$pattern = '/\[([0-9]+)\]/';
	
	if (preg_match_all($pattern, $text, $matches, PREG_SET_ORDER) > 0)
	{		
		foreach($matches as $match)
		{		
			$svnID = $match[1];
			if (!isSet($lookupTable[$svnID]))
			{
				echo "Warning: unknown GIT hash for SVN revision $svnID\n";
				continue;
			}
			$gitID = substr($lookupTable[$svnID], 0, $nrHashCharacters);
			
			$text = str_replace('[' . $svnID . ']', '[' . $gitID . '] (SVN [changeset:' . $svnID . '/oldsvn r' . $svnID . '])', $text);
		}
		
		return true;
	}
	
	return false;
}

echo "Creating SVN -> GIT conversion table table...\n";

// Create the lookup table
$lines = file($pathLookupTable);
foreach ($lines as $line)
{	
	if (empty($line)) continue;	
	list ($svnID, $gitID) = explode("\t", trim($line));	
	$lookupTable[$svnID] = $gitID;
}

// Connect to the TRAC database
$db = new PDO($DBString,$DBUser,$DBPasswd);

echo "Converting table 'ticket_change'...\n";

// Convert table 'ticket_change'
$result = $db->query('SELECT * FROM ticket_change'); 

$i = 1;
foreach ($result as $row)
{
	$i++;
	// Only update when there is something to be changed, since SQLite isn't the fastest beast around
	if (convertSVNIDToGitID($row['oldvalue'], $lookupTable, $nrHashCharacters) || convertSVNIDToGitID($row['newvalue'], $lookupTable, $nrHashCharacters))
	{	
		$query = $db->prepare("UPDATE ticket_change SET oldvalue=?, newvalue=? WHERE ticket = ? AND time = ? AND author=? AND field=?");
		$query->bindParam(1, $row['oldvalue']);
		$query->bindParam(2, $row['newvalue']);
		$query->bindParam(3, $row['ticket']);
		$query->bindParam(4, $row['time']);
		$query->bindParam(5, $row['author']);
		$query->bindParam(6, $row['field']);

		if (!$query->execute())
		{
			echo "Query failed: " . $query . "\n";
		}		
		
		echo "Updated ticket_change $i\n";
	}
}

echo "Converting table 'ticket'...\n";

// Convert table 'ticket'

$i = 1;

$result = $db->query('SELECT * FROM ticket');
foreach ($result as $row)
{
	if (convertSVNIDToGitID($row['description'], $lookupTable, $nrHashCharacters))
	{	
		$query = $db->prepare("UPDATE ticket SET description=? WHERE id = ?");
		$query->bindParam(1, $row['description']);
		$query->bindParam(2, $row['id']);

		if (!$query->execute())
		{
			echo "Query failed: " . $query . "\n";
		}

		echo "Updated ticket " . $row['id']. "\n";

	}
}

// Done :)
echo "Done!\n";
?>
