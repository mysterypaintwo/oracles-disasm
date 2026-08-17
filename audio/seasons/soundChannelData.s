m_section_superfree AudioData1

snddeStart:

snddeChannel0:
snddeChannel1:
snddeChannel4:
snddeChannel6:
	cmdff


snd97Start:
snda1Start:
sndadStart:
sndb6Start:

snd97Channel2:
snd97Channel7:
snda1Channel2:
snda1Channel7:
sndadChannel2:
sndadChannel7:
sndb6Channel2:
sndb6Channel7:
bank39ChannelFallback:
	cmdff

.redefine MUSIC_CHANNEL_FALLBACK bank39ChannelFallback


.include "audio/common/sfx/bin/fairyCutscene.s"
.include "audio/common/sfx/bin/baseball.s"

.ifdef BUILD_VANILLA
	.dsb 12 $ff
.endif

.include "audio/common/sfx/bin/beam.s"
.include "audio/common/sfx/bin/breakRock.s"
.include "audio/common/sfx/bin/wave.s"
.include "audio/common/sfx/bin/swordObtained.s"
.include "audio/seasons/sfx/bin/magnetGloves.s"
.include "audio/common/sfx/bin/pieceOfPower.s"
.include "audio/common/sfx/bin/linkSwim.s"
.include "audio/common/sfx/bin/poof.s"
.include "audio/common/sfx/bin/bigSword.s"
.include "audio/seasons/sfx/bin/unknownb5.s" ; TODO
.include "audio/common/sfx/bin/rumble.s"
.include "audio/seasons/sfx/bin/frypolarMovement.s"
.include "audio/common/sfx/bin/veranProjectile.s"
.include "audio/common/sfx/bin/shock.s"
.include "audio/common/sfx/bin/beam1.s"
.include "audio/common/sfx/bin/fadeout.s"
.include "audio/common/sfx/bin/pickUp.s"
.include "audio/common/sfx/bin/chicken.s"
.include "audio/common/sfx/bin/makuDisappear.s"
.include "audio/common/sfx/bin/beam2.s"
.include "audio/seasons/sfx/bin/unknownb7.s" ; TODO
.include "audio/common/sfx/bin/veranFairyAttack.s"
.include "audio/common/sfx/bin/rumble2.s"
.include "audio/common/sfx/bin/opening.s"
.include "audio/common/sfx/bin/warpStart.s"
.include "audio/common/sfx/bin/endless.s"
.include "audio/common/sfx/bin/bigExplosion2.s"
.include "audio/seasons/sfx/bin/unknownbd.s" ; TODO
.include "audio/common/mus/bin/mapleGame.s"
.include "audio/common/mus/bin/finalBoss.s"
.include "audio/common/mus/bin/essence.s"

.ifdef BUILD_VANILLA
	.dsb 13 $ff
.endif

.ends


.BANK $3a SLOT 1
.ORG 0

m_section_superfree AudioData2

mus41Start:
mus42Start:

mus41Channel0:
mus41Channel1:
mus41Channel4:
mus41Channel6:
mus42Channel0:
mus42Channel1:
mus42Channel4:
mus42Channel6:
bank3aChannelFallback:
	cmdff

.redefine MUSIC_CHANNEL_FALLBACK bank3aChannelFallback


.include "audio/common/mus/bin/indoors.s"
.include "audio/common/mus/bin/titlescreen.s"
; Sound index 0 (dumpMusic.py's original, unhelpfully-named "musNone") and index 1
; ("musTitlescreen") share identical channel data in the original ROM -- both really are
; the title screen theme. A single mml2wla run only emits one label set (this one, the
; correctly-named "Titlescreen"), so the other index's labels are aliased onto it here.
.define musNoneStart musTitlescreenStart EXPORT
.define musNoneChannel0 musTitlescreenChannel0 EXPORT
.define musNoneChannel1 musTitlescreenChannel1 EXPORT
.define musNoneChannel4 musTitlescreenChannel4 EXPORT
.define musNoneChannel6 MUSIC_CHANNEL_FALLBACK EXPORT
.include "audio/common/mus/bin/miniboss.s"
.include "audio/common/mus/bin/gameover.s"
.include "audio/common/mus/bin/cave.s"
.include "audio/common/mus/bin/getEssence.s"
.include "audio/common/sfx/bin/selectItem.s"
.include "audio/common/sfx/bin/solvePuzzle.s"
.include "audio/common/sfx/bin/getItem.s"
.include "audio/common/sfx/bin/chargeSword.s"
.include "audio/common/sfx/bin/clink.s"
.include "audio/common/sfx/bin/throw.s"
.include "audio/common/sfx/bin/bombLand.s"
.include "audio/common/sfx/bin/jump.s"
.include "audio/common/sfx/bin/damageEnemy.s"
.include "audio/common/sfx/bin/gainHeart.s"
.include "audio/common/sfx/bin/clink2.s"
.include "audio/common/sfx/bin/fallInHole.s"
.include "audio/common/sfx/bin/error.s"
.include "audio/common/sfx/bin/solvePuzzle2.s"
.include "audio/common/sfx/bin/getSeed.s"
.include "audio/common/sfx/bin/damageLink.s"
.include "audio/common/sfx/bin/heartBeep.s"
.include "audio/common/sfx/bin/rupee.s"
.include "audio/common/sfx/bin/gohmaSpawnGel.s"
.include "audio/seasons/sfx/bin/freezeLava.s"
.include "audio/common/sfx/bin/slash.s"
.include "audio/common/sfx/bin/swordSpin.s"
.include "audio/common/sfx/bin/openChest.s"
.include "audio/common/sfx/bin/cutGrass.s"
.include "audio/common/sfx/bin/enterCave.s"
.include "audio/common/sfx/bin/bigExplosion.s"
.include "audio/common/sfx/bin/boomerang.s"
.include "audio/common/sfx/bin/dropEssence.s"
.include "audio/common/sfx/bin/shield.s"
.include "audio/common/sfx/bin/unknown5.s"
.include "audio/common/sfx/bin/swordSlash.s"
.include "audio/common/sfx/bin/killEnemy.s"
.include "audio/common/sfx/bin/openMenu.s"
.include "audio/common/sfx/bin/closeMenu.s"
.include "audio/common/sfx/bin/energyThing.s"
.include "audio/common/sfx/bin/swordBeam.s"
.include "audio/common/sfx/bin/linkDead.s"
.include "audio/common/sfx/bin/linkFall.s"
.include "audio/common/sfx/bin/text.s"
.include "audio/common/sfx/bin/bossDamage.s"
.include "audio/common/sfx/bin/explosion.s"
.include "audio/common/sfx/bin/doorClose.s"
.include "audio/common/sfx/bin/moveBlock.s"
.include "audio/common/sfx/bin/lightTorch.s"
.include "audio/common/sfx/bin/unknown3.s"
.include "audio/common/sfx/bin/minecart.s"
.include "audio/common/sfx/bin/strongPound.s"
.include "audio/common/sfx/bin/roller.s"
.include "audio/common/sfx/bin/mysterySeed.s"
.include "audio/seasons/sfx/bin/unknown7d.s" ; TODO
.include "audio/common/sfx/bin/switch.s"
.include "audio/common/sfx/bin/aquamentusHover.s"
.include "audio/common/sfx/bin/unknown4.s"
.include "audio/common/sfx/bin/bossDead.s"
.include "audio/common/sfx/bin/lightning.s"
.include "audio/common/sfx/bin/wind.s"
.include "audio/seasons/sfx/bin/unknownd1.s" ; TODO
.include "audio/common/sfx/bin/pirateBell.s"
.include "audio/seasons/sfx/bin/dodongoOpenMouth.s"
.include "audio/common/sfx/bin/magicPowder.s"
.include "audio/common/sfx/bin/menuMove.s"
.include "audio/common/sfx/bin/scentSeed.s"
.include "audio/seasons/sfx/bin/unknown86.s" ; TODO
.include "audio/common/sfx/bin/teleport.s"

sndd4Start:
sndd4Channel2:
	cmdff
sndd4Channel7:
	cmdff

sndd5Start:
sndd5Channel2:
	cmdff

.include "audio/common/sfx/bin/transform.s"
.include "audio/common/sfx/bin/blueStalfosCharge.s"
.include "audio/seasons/sfx/bin/makuTreeSnore.s"
.include "audio/common/sfx/bin/fluteRicky.s"
.include "audio/common/sfx/bin/fluteDimitri.s"
.include "audio/common/sfx/bin/fluteMoosh.s"
.include "audio/common/mus/bin/preCredits.s"
.include "audio/common/mus/bin/twinrova.s"
.include "audio/common/sfx/bin/makuTreePast.s"
.include "audio/common/sfx/bin/restore.s"
.include "audio/seasons/sfx/bin/creepyLaugh.s"
.include "audio/common/sfx/bin/moosh.s"
.include "audio/common/sfx/bin/ding.s"
.include "audio/common/sfx/bin/dekuScrub.s"
.include "audio/common/sfx/bin/floodgates.s"
.include "audio/common/sfx/bin/ricky.s"
.include "audio/common/sfx/bin/circling.s"
.include "audio/common/sfx/bin/dig.s"

.ifdef BUILD_VANILLA
	.dsb 4 $ff
.endif

.ends


.BANK $3b SLOT 1
.ORG 0

m_section_superfree AudioData3

mus43Start:
mus44Start:
mus45Start:

mus43Channel0:
mus43Channel1:
mus43Channel4:
mus43Channel6:
mus44Channel0:
mus44Channel1:
mus44Channel4:
mus44Channel6:
mus45Channel0:
mus45Channel1:
mus45Channel4:
mus45Channel6:
bank3bChannelFallback:
	cmdff

.redefine MUSIC_CHANNEL_FALLBACK bank3bChannelFallback


.include "audio/seasons/mus/bin/horonVillage.s"
.include "audio/common/mus/bin/minigame.s"
.include "audio/common/mus/bin/fileSelect.s"
.include "audio/common/mus/bin/fairyFountain.s"
.include "audio/common/mus/bin/overworld.s"
.include "audio/seasons/mus/bin/hideAndSeek.s"
.include "audio/seasons/mus/bin/sunkenCity.s"
.include "audio/common/mus/bin/essenceRoom.s"
.include "audio/seasons/mus/bin/templeRemains.s"
.include "audio/seasons/mus/bin/unused1.s"
.include "audio/seasons/mus/bin/tarmRuins.s"
.include "audio/seasons/mus/bin/carnival.s"
.include "audio/common/mus/bin/ganon.s"
.include "audio/seasons/mus/bin/samasaDesert.s"
.include "audio/common/sfx/bin/splash.s"
.include "audio/common/sfx/bin/text2.s"
.include "audio/common/sfx/bin/filledHeartContainer.s"
.include "audio/common/sfx/bin/seedShooter.s"
.include "audio/common/sfx/bin/unknown7.s"
.include "audio/seasons/sfx/bin/unknown8e.s" ; TODO
.include "audio/common/sfx/bin/enemyJump.s"
.include "audio/common/sfx/bin/galeSeed.s"

.ifdef BUILD_VANILLA
	.dsb 10 $ff
.endif

.ends


.BANK $3c SLOT 1
.ORG 0

m_section_superfree AudioData4

bank3cChannelFallback:
	cmdff

.redefine MUSIC_CHANNEL_FALLBACK bank3cChannelFallback


.include "audio/seasons/mus/bin/makuTree.s"
.include "audio/seasons/mus/bin/swordAndShieldMaze.s"
.include "audio/seasons/mus/bin/gnarledRootDungeon.s"
.include "audio/seasons/mus/bin/snakesRemains.s"
.include "audio/seasons/mus/bin/herosCave.s"
.include "audio/seasons/mus/bin/explorersCrypt.s"
.include "audio/seasons/mus/bin/unicornsCave.s"
.include "audio/seasons/mus/bin/poisonMothsLair.s"
.include "audio/seasons/mus/bin/dancingDragonDungeon.s"
.include "audio/common/mus/bin/onoxCastle.s"
.include "audio/seasons/mus/bin/subrosianDance.s"
.include "audio/seasons/mus/bin/ancientRuins.s"
.include "audio/common/mus/bin/sadness.s"
.include "audio/common/mus/bin/intro2.s"
.include "audio/common/sfx/bin/goron.s"
.include "audio/common/sfx/bin/ghost.s"
.include "audio/common/sfx/bin/becomeBaby.s"
.include "audio/common/sfx/bin/jingle.s"
.include "audio/common/sfx/bin/strike.s"

.ifdef BUILD_VANILLA
	.dsb 4 $ff
.endif

.ends


.BANK $3d SLOT 1
.ORG 0

m_section_superfree AudioData5

bank3dChannelFallback:
mus24Channel6:
	cmdff

.redefine MUSIC_CHANNEL_FALLBACK bank3dChannelFallback

.include "audio/common/mus/bin/triumphant.s"
.include "audio/common/mus/bin/disaster.s"

mus24Start:
mus24Channel1:
	cmdff
mus24Channel0:
	cmdff
mus24Channel4:
	cmdff

.include "audio/seasons/mus/bin/pirates.s"
.include "audio/common/mus/bin/finalDungeon.s"
.include "audio/seasons/mus/bin/subrosianShop.s"
; dumpMusic.py's original dump used the "snd" (not "mus") label prefix for this song's
; sound-pointer entry -- mml2wla always emits "mus" (see emit_song), so alias to what
; soundPointers.s/soundChannelPointers.s already reference by name.
.define sndSubrosianShopStart musSubrosianShopStart EXPORT
.define sndSubrosianShopChannel0 musSubrosianShopChannel0 EXPORT
.define sndSubrosianShopChannel1 musSubrosianShopChannel1 EXPORT
.define sndSubrosianShopChannel4 musSubrosianShopChannel4 EXPORT
.define sndSubrosianShopChannel6 musSubrosianShopChannel6 EXPORT
.include "audio/common/mus/bin/rosaDate.s"
.include "audio/common/mus/bin/roomOfRites.s"
.include "audio/common/mus/bin/blackTowerEntrance.s"
.include "audio/common/mus/bin/zeldaSaved.s"
.include "audio/common/mus/bin/mapleTheme.s"
.include "audio/common/mus/bin/intro1.s"
.include "audio/common/mus/bin/crazyDance.s"
.include "audio/seasons/sfx/bin/unknown93.s"
.include "audio/seasons/sfx/bin/dodongoEat.s"
.include "audio/common/sfx/bin/compass.s"
.include "audio/common/sfx/bin/land.s"
.include "audio/common/sfx/bin/switchHook.s"

.ifdef BUILD_VANILLA
	.dsb 4 $ff
.endif

.ends


.BANK $3e SLOT 1
.ORG 0

m_section_superfree AudioData6

mus30Start:
mus37Start:
mus3aStart:
mus3bStart:
mus47Start:
mus48Start:
mus49Start:
mus4bStart:

mus30Channel4:
mus30Channel6:
mus37Channel4:
mus3aChannel6:
mus3bChannel0:
mus3bChannel1:
mus3bChannel4:
mus3bChannel6:
mus47Channel0:
mus47Channel1:
mus47Channel4:
mus47Channel6:
mus48Channel0:
mus48Channel1:
mus48Channel4:
mus48Channel6:
mus49Channel0:
mus49Channel1:
mus49Channel4:
mus49Channel6:
mus4bChannel0:
mus4bChannel1:
mus4bChannel4:
mus4bChannel6:
bank3eChannelFallback:
	cmdff

.redefine MUSIC_CHANNEL_FALLBACK bank3eChannelFallback

.include "audio/seasons/sfx/bin/danceMove.s"
.include "audio/common/sfx/bin/dimitri.s"
.include "audio/common/sfx/bin/whistle.s"
.include "audio/common/sfx/bin/goronDanceB.s"

; Undefined sounds
sndd6Start:
sndd7Start:
sndd8Start:
sndd9Start:
snddaStart:
snddbStart:
snddcStart:
sndddStart:

sndd6Channel1:
sndd7Channel1:
sndd8Channel1:
sndd9Channel1:
snddaChannel1:
snddbChannel1:
snddcChannel1:
sndddChannel1:
	cmdff

sndd6Channel0:
sndd7Channel0:
sndd8Channel0:
sndd9Channel0:
snddaChannel0:
snddbChannel0:
snddcChannel0:
sndddChannel0:
	cmdff

sndd6Channel4:
sndd7Channel4:
sndd8Channel4:
sndd9Channel4:
snddaChannel4:
snddbChannel4:
snddcChannel4:
sndddChannel4:
	cmdff

sndd6Channel6:
sndd7Channel6:
sndd8Channel6:
sndd9Channel6:
snddaChannel6:
snddbChannel6:
snddcChannel6:
sndddChannel6:
	cmdff

.include "audio/common/mus/bin/greatMoblin.s"

mus37Channel1:
	cmdff
mus37Channel0:
	cmdff
mus37Channel6:
	cmdff

mus30Channel1:
	cmdff
mus30Channel0:
	cmdff

.include "audio/common/mus/bin/ladxSideview.s"
.include "audio/common/mus/bin/syrup.s"
.include "audio/seasons/mus/bin/songOfStorms.s"
.include "audio/common/mus/bin/goronCave.s"
.include "audio/common/mus/bin/credits2.s"
.include "audio/common/mus/bin/boss.s"

mus3aChannel1:
	cmdff
mus3aChannel0:
	cmdff
mus3aChannel4:
	cmdff

.ifdef BUILD_VANILLA
	.dsb 7 $ff
.endif

.include "audio/seasons/mus/bin/subrosia.s"
.include "audio/common/mus/bin/credits1.s"
.include "audio/seasons/mus/bin/unused2.s"

.ifdef BUILD_VANILLA
	.dsb 10 $ff
.endif

.ends


.undefine MUSIC_CHANNEL_FALLBACK
